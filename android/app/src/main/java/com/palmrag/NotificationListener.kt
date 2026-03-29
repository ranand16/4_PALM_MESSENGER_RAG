package com.palmrag

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import androidx.work.*
import com.palmrag.db.AppDatabase
import com.palmrag.db.NotificationEntity
import com.palmrag.sync.NotificationSyncWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit

class NotificationListener : NotificationListenerService() {

    companion object {
        private const val TAG = "PalmRAG_Listener"

        // Whitelist of package names to capture
        val WATCHED_PACKAGES = setOf(
            "com.whatsapp",
            "com.whatsapp.w4b",
            "org.telegram.messenger",
            "org.thoughtcrime.securesms",   // Signal
            "com.google.android.apps.messaging", // Google Messages
            "com.facebook.orca",             // Messenger
            "com.instagram.android",
            "com.slack",
            "com.discord"
        )
    }

    private val scope = CoroutineScope(Dispatchers.IO)

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (!isWatched(sbn.packageName)) return

        val extras = sbn.notification.extras
        val title = extras.getCharSequence("android.title")?.toString() ?: ""
        val text = extras.getCharSequence("android.text")?.toString() ?: ""
        val bigText = extras.getCharSequence("android.bigText")?.toString() ?: ""

        // Skip empty notifications
        if (title.isBlank() && text.isBlank()) return

        Log.d(TAG, "Captured: ${sbn.packageName} | $title | $text")

        val entity = NotificationEntity(
            packageName = sbn.packageName,
            title = title,
            text = if (bigText.isNotBlank()) bigText else text,
            timestamp = sbn.postTime
        )

        scope.launch {
            try {
                AppDatabase.getInstance(applicationContext).notificationDao().insert(entity)
                scheduleSync()
            } catch (e: Exception) {
                Log.e(TAG, "Failed to store notification", e)
            }
        }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        // No-op
    }

    private fun isWatched(packageName: String): Boolean {
        val prefs = getSharedPreferences("palm_rag_prefs", MODE_PRIVATE)
        val customPackages = prefs.getStringSet("watched_packages", null)
        val watchList = customPackages ?: WATCHED_PACKAGES
        return packageName in watchList
    }

    private fun scheduleSync() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val syncRequest = PeriodicWorkRequestBuilder<NotificationSyncWorker>(
            15, TimeUnit.MINUTES
        )
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(applicationContext)
            .enqueueUniquePeriodicWork(
                "notification_sync",
                ExistingPeriodicWorkPolicy.KEEP,
                syncRequest
            )
    }
}
