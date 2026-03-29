package com.palmrag.sync

import android.content.Context
import android.os.Build
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.palmrag.api.ApiClient
import com.palmrag.api.NotificationBatch
import com.palmrag.api.NotificationDTO
import com.palmrag.db.AppDatabase

class NotificationSyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "PalmRAG_Sync"
    }

    override suspend fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("palm_rag_prefs", Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("backend_url", null)
        val apiKey = prefs.getString("api_key", null)

        if (baseUrl.isNullOrBlank() || apiKey.isNullOrBlank()) {
            Log.w(TAG, "Backend URL or API key not configured, skipping sync")
            return Result.retry()
        }

        return try {
            val db = AppDatabase.getInstance(applicationContext)
            val unsynced = db.notificationDao().getUnsynced()

            if (unsynced.isEmpty()) {
                Log.d(TAG, "No unsynced notifications")
                return Result.success()
            }

            val deviceId = Build.MODEL + "_" + Build.ID
            val batch = NotificationBatch(
                notifications = unsynced.map { entity ->
                    NotificationDTO(
                        package_name = entity.packageName,
                        title = entity.title,
                        text = entity.text,
                        timestamp = entity.timestamp,
                        device_id = deviceId
                    )
                },
                device_id = deviceId
            )

            val api = ApiClient.getApi(baseUrl)
            val response = api.sendNotifications(apiKey, batch)

            if (response.isSuccessful) {
                val syncedIds = unsynced.map { it.id }
                db.notificationDao().markSynced(syncedIds)
                Log.d(TAG, "Synced ${syncedIds.size} notifications")

                // Clean notifications older than 7 days
                val sevenDaysAgo = System.currentTimeMillis() - 7 * 24 * 60 * 60 * 1000L
                db.notificationDao().cleanOld(sevenDaysAgo)

                Result.success()
            } else {
                Log.e(TAG, "Sync failed: ${response.code()} ${response.message()}")
                Result.retry()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Sync error", e)
            Result.retry()
        }
    }
}
