/**
 * NotificationListener.kt — Notification Capture Service
 *
 * This module provides a NotificationListenerService that intercepts incoming
 * notifications from whitelisted messaging apps (WhatsApp, Telegram, Signal,
 * Messenger, Instagram, Slack, Discord, etc.) and persists them to a local
 * Room database. It also schedules periodic background sync via WorkManager
 * to push captured notifications to the backend API.
 *
 * Android requires the user to explicitly grant Notification Access permission
 * in system settings for this service to receive notification events.
 */
package com.palmrag

// Android notification listener service framework
import android.service.notification.NotificationListenerService
// Represents a notification posted in the status bar
import android.service.notification.StatusBarNotification
// Android logging utility
import android.util.Log
// WorkManager classes for background task scheduling
import androidx.work.*
// Local Room database for storing captured notifications
import com.palmrag.db.AppDatabase
// Room entity representing a single notification row
import com.palmrag.db.NotificationEntity
// Background sync worker that pushes notifications to the backend
import com.palmrag.sync.NotificationSyncWorker
// Kotlin coroutine scope for launching async operations
import kotlinx.coroutines.CoroutineScope
// IO dispatcher optimized for disk/network I/O operations
import kotlinx.coroutines.Dispatchers
// Coroutine builder for launching non-blocking async tasks
import kotlinx.coroutines.launch
// Java time unit for specifying sync interval
import java.util.concurrent.TimeUnit

/**
 * NotificationListener — Android service that captures notifications from messaging apps.
 *
 * Extends [NotificationListenerService] to receive system-level notification events.
 * Filters notifications to only capture messages from known messaging apps defined
 * in [WATCHED_PACKAGES]. Stores each captured notification in the local Room database
 * and ensures a periodic sync worker is scheduled to push data to the backend.
 */
class NotificationListener : NotificationListenerService() {

    /**
     * Companion object holding static constants and default configuration
     * shared across all instances of NotificationListener.
     */
    companion object {
        // Log tag used for all log messages from this service
        private const val TAG = "PalmRAG_Listener"

        // Default whitelist of Android package names for messaging apps to capture
        // These are the well-known package names for popular messaging platforms
        val WATCHED_PACKAGES = setOf(
            "com.whatsapp",                         // WhatsApp Messenger
            "com.whatsapp.w4b",                     // WhatsApp Business
            "org.telegram.messenger",               // Telegram
            "org.thoughtcrime.securesms",            // Signal Private Messenger
            "com.google.android.apps.messaging",     // Google Messages (SMS/RCS)
            "com.facebook.orca",                     // Facebook Messenger
            "com.instagram.android",                 // Instagram (DMs)
            "com.slack",                             // Slack
            "com.discord"                            // Discord
        )
    }

    // Coroutine scope using IO dispatcher for database write operations
    private val scope = CoroutineScope(Dispatchers.IO)

    /**
     * Called by the system when a new notification is posted to the status bar.
     * Filters by watched package, extracts notification content, and stores it
     * in the local Room database for later sync to the backend.
     *
     * @param sbn The [StatusBarNotification] containing the notification data
     */
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        // Skip notifications from apps not in the watch list
        if (!isWatched(sbn.packageName)) return

        // Extract notification content from the extras bundle
        val extras = sbn.notification.extras
        // Get the notification title (e.g., sender name); default to empty string if null
        val title = extras.getCharSequence("android.title")?.toString() ?: ""
        // Get the short text content of the notification; default to empty string if null
        val text = extras.getCharSequence("android.text")?.toString() ?: ""
        // Get expanded "big text" content (longer message body); default to empty string if null
        val bigText = extras.getCharSequence("android.bigText")?.toString() ?: ""

        // Skip notifications that have neither title nor text content
        if (title.isBlank() && text.isBlank()) return

        // Log the captured notification details for debugging
        Log.d(TAG, "Captured: ${sbn.packageName} | $title | $text")

        // Create a NotificationEntity for Room database storage
        // Prefer bigText over text when available (contains the full message body)
        val entity = NotificationEntity(
            packageName = sbn.packageName,       // Source app's Android package name
            title = title,                        // Notification title (sender/subject)
            text = if (bigText.isNotBlank()) bigText else text,  // Full message or short text
            timestamp = sbn.postTime              // Timestamp when the notification was posted (Unix ms)
        )

        // Launch a coroutine on the IO dispatcher to perform the database insertion
        scope.launch {
            try {
                // Insert the notification entity into the local Room database
                AppDatabase.getInstance(applicationContext).notificationDao().insert(entity)
                // Ensure the periodic sync worker is scheduled to push data to the backend
                scheduleSync()
            } catch (e: Exception) {
                // Log any errors during database insertion without crashing the service
                Log.e(TAG, "Failed to store notification", e)
            }
        }
    }

    /**
     * Called by the system when a notification is removed from the status bar.
     * No action is needed — we only care about capturing new notifications.
     *
     * @param sbn The [StatusBarNotification] that was removed
     */
    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        // No-op: removal events are not relevant for notification capture
    }

    /**
     * Checks whether a given package name is in the current watch list.
     * First checks SharedPreferences for a user-customized package set;
     * falls back to the default [WATCHED_PACKAGES] if none is configured.
     *
     * @param packageName The Android package name to check
     * @return true if the package is being watched, false otherwise
     */
    private fun isWatched(packageName: String): Boolean {
        // Read SharedPreferences for any user-customized watch list
        val prefs = getSharedPreferences("palm_rag_prefs", MODE_PRIVATE)
        // Attempt to load a custom set of watched packages (null if not configured)
        val customPackages = prefs.getStringSet("watched_packages", null)
        // Use custom packages if available, otherwise fall back to the default set
        val watchList = customPackages ?: WATCHED_PACKAGES
        // Check if the given package name exists in the active watch list
        return packageName in watchList
    }

    /**
     * Schedules a periodic WorkManager task to sync unsynced notifications
     * to the backend API. Uses a 15-minute interval (minimum allowed by WorkManager)
     * and requires an active network connection.
     *
     * Uses [ExistingPeriodicWorkPolicy.KEEP] to avoid creating duplicate workers
     * if one is already enqueued.
     */
    private fun scheduleSync() {
        // Build constraints: require network connectivity before running the sync
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)  // Only sync when network is available
            .build()

        // Create a periodic work request that runs NotificationSyncWorker every 15 minutes
        val syncRequest = PeriodicWorkRequestBuilder<NotificationSyncWorker>(
            15, TimeUnit.MINUTES     // Minimum interval supported by WorkManager
        )
            .setConstraints(constraints)  // Apply the network connectivity constraint
            .build()

        // Enqueue the periodic work, using KEEP policy to prevent duplicate workers
        WorkManager.getInstance(applicationContext)
            .enqueueUniquePeriodicWork(
                "notification_sync",                    // Unique work name to identify this task
                ExistingPeriodicWorkPolicy.KEEP,        // Keep existing worker if already scheduled
                syncRequest                              // The periodic work request to enqueue
            )
    }
}
