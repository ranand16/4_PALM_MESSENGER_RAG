/**
 * NotificationSyncWorker.kt — Periodic Background Sync Worker
 *
 * This module implements a WorkManager [CoroutineWorker] that runs periodically
 * (every 15 minutes) to sync unsynced notifications from the local Room database
 * to the backend API. It handles the complete sync lifecycle:
 *
 * 1. Read backend URL and API key from SharedPreferences
 * 2. Query unsynced notifications from Room (batch of up to 100)
 * 3. Map entities to DTOs and construct a batch with device ID
 * 4. Send the batch to the backend via Retrofit API call
 * 5. Mark successfully synced notifications in the local DB
 * 6. Clean up synced notifications older than 7 days
 *
 * Scheduled by [NotificationListener.scheduleSync] with network connectivity constraint.
 */
package com.palmrag.sync

// Android Context for SharedPreferences access
import android.content.Context
// Android Build info for generating device identifiers
import android.os.Build
// Android logging utility
import android.util.Log
// WorkManager CoroutineWorker base class for async background work
import androidx.work.CoroutineWorker
// WorkManager parameters passed to the worker by the framework
import androidx.work.WorkerParameters
// Singleton Retrofit client for backend API communication
import com.palmrag.api.ApiClient
// DTO for batching notifications into a single API request
import com.palmrag.api.NotificationBatch
// DTO representing a single notification for the API request body
import com.palmrag.api.NotificationDTO
// Room database singleton for local notification storage
import com.palmrag.db.AppDatabase

/**
 * NotificationSyncWorker — Background worker that syncs local notifications to the backend.
 *
 * Extends [CoroutineWorker] to run on a background thread via WorkManager.
 * Reads configuration from SharedPreferences, queries unsynced notifications,
 * sends them in a batch to the backend API, and performs cleanup on success.
 *
 * @param context The application context provided by WorkManager
 * @param params Worker parameters from the WorkManager framework
 */
class NotificationSyncWorker(
    context: Context,       // Application context for accessing SharedPreferences and Room DB
    params: WorkerParameters // Worker parameters containing input data and run attempt count
) : CoroutineWorker(context, params) {

    /**
     * Companion object with static constants for the sync worker.
     */
    companion object {
        // Log tag used for all log messages from this worker
        private const val TAG = "PalmRAG_Sync"
    }

    /**
     * Main entry point for the sync worker, called by WorkManager on a background thread.
     * Implements the full sync lifecycle: config check → query → batch → send → mark → clean.
     *
     * @return [Result.success] if sync completes, [Result.retry] if config missing or API fails
     */
    override suspend fun doWork(): Result {
        // Read sync configuration from SharedPreferences
        val prefs = applicationContext.getSharedPreferences("palm_rag_prefs", Context.MODE_PRIVATE)
        // Get the backend server URL (e.g., "http://192.168.1.100:8000")
        val baseUrl = prefs.getString("backend_url", null)
        // Get the API key for authenticating with the backend
        val apiKey = prefs.getString("api_key", null)

        // Skip sync if backend URL or API key hasn't been configured by the user yet
        if (baseUrl.isNullOrBlank() || apiKey.isNullOrBlank()) {
            Log.w(TAG, "Backend URL or API key not configured, skipping sync")
            return Result.retry()  // Retry later in case user configures settings
        }

        return try {
            // Get the Room database singleton instance
            val db = AppDatabase.getInstance(applicationContext)
            // Query up to 100 unsynced notifications from the local database
            val unsynced = db.notificationDao().getUnsynced()

            // If there are no unsynced notifications, nothing to do — return success
            if (unsynced.isEmpty()) {
                Log.d(TAG, "No unsynced notifications")
                return Result.success()
            }

            // Generate a device identifier from the device model and build ID
            val deviceId = Build.MODEL + "_" + Build.ID
            // Create a NotificationBatch DTO by mapping each entity to a NotificationDTO
            val batch = NotificationBatch(
                notifications = unsynced.map { entity ->
                    // Convert each Room entity to an API-compatible DTO
                    NotificationDTO(
                        package_name = entity.packageName,  // Source app package name
                        title = entity.title,                // Notification title text
                        text = entity.text,                  // Notification body text
                        timestamp = entity.timestamp,        // Original post time in Unix ms
                        device_id = deviceId                 // Device identifier for this notification
                    )
                },
                device_id = deviceId  // Device identifier for the batch-level field
            )

            // Get the Retrofit API client configured with the user's backend URL
            val api = ApiClient.getApi(baseUrl)
            // Send the notification batch to the backend API with authentication
            val response = api.sendNotifications(apiKey, batch)

            // Check if the backend API returned a successful HTTP response (2xx)
            if (response.isSuccessful) {
                // Extract the IDs of all synced notifications for bulk status update
                val syncedIds = unsynced.map { it.id }
                // Mark all synced notifications as uploaded in the local database
                db.notificationDao().markSynced(syncedIds)
                // Log the number of successfully synced notifications
                Log.d(TAG, "Synced ${syncedIds.size} notifications")

                // Clean up: delete synced notifications older than 7 days to free storage
                val sevenDaysAgo = System.currentTimeMillis() - 7 * 24 * 60 * 60 * 1000L
                // Remove old synced records from the local database
                db.notificationDao().cleanOld(sevenDaysAgo)

                // Return success to WorkManager — worker completed normally
                Result.success()
            } else {
                // Log the HTTP error code and message for debugging failed sync
                Log.e(TAG, "Sync failed: ${response.code()} ${response.message()}")
                // Return retry to tell WorkManager to reschedule this work
                Result.retry()
            }
        } catch (e: Exception) {
            // Catch any unexpected errors (network, parsing, database) and log them
            Log.e(TAG, "Sync error", e)
            // Return retry so WorkManager will attempt the sync again later
            Result.retry()
        }
    }
}
    }
}
