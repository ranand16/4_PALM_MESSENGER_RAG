package com.palmrag.notificationlistener

import android.content.pm.PackageManager
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.Executors
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * NotificationForwarderService
 *
 * Listens for all incoming notifications. When a notification arrives from a
 * monitored messaging app (WhatsApp, Telegram, Signal, …) it is forwarded as a
 * JSON POST request to the configured backend server.
 *
 * The user must grant "Notification access" in system Settings for this service
 * to receive notifications.
 */
class NotificationForwarderService : NotificationListenerService() {

    private val executor = Executors.newSingleThreadExecutor()
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
        .writeTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
        .build()

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val packageName = sbn.packageName ?: return

        // Only forward notifications from monitored apps
        if (!MONITORED_PACKAGES.contains(packageName)) return

        val extras = sbn.notification?.extras ?: return
        val title = extras.getString("android.title") ?: ""
        val text  = extras.getCharSequence("android.text")?.toString() ?: return
        if (text.isBlank()) return

        val appLabel = appLabel(packageName)
        val timestamp = java.time.Instant.ofEpochMilli(sbn.postTime).toString()

        val payload = JSONObject().apply {
            put("app", appLabel)
            put("sender", title)
            put("content", text)
            put("timestamp", timestamp)
        }

        val serverUrl = serverUrl() ?: run {
            Log.w(TAG, "Server URL not configured – notification dropped.")
            return
        }

        executor.execute { postNotification("$serverUrl/notifications", payload) }
    }

    override fun onListenerDisconnected() {
        executor.shutdown()
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private fun serverUrl(): String? {
        val prefs = getSharedPreferences(MainActivity.PREFS_NAME, MODE_PRIVATE)
        val url = prefs.getString(MainActivity.KEY_SERVER_URL, null)
        return if (url.isNullOrBlank()) null else url
    }

    private fun appLabel(packageName: String): String {
        return PACKAGE_TO_LABEL[packageName] ?: try {
            val pm = packageManager
            val info = pm.getApplicationInfo(packageName, 0)
            pm.getApplicationLabel(info).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            packageName
        }
    }

    private fun postNotification(url: String, payload: JSONObject) {
        val body = payload.toString().toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder().url(url).post(body).build()
        try {
            httpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    Log.e(TAG, "Server returned HTTP ${response.code} for notification POST.")
                }
            }
        } catch (e: IOException) {
            Log.e(TAG, "Failed to POST notification: ${e.message}")
        }
    }

    companion object {
        private const val TAG = "NotifForwarder"

        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        /** Package names of apps whose notifications should be forwarded. */
        val MONITORED_PACKAGES = setOf(
            "com.whatsapp",
            "com.whatsapp.w4b",          // WhatsApp Business
            "org.telegram.messenger",
            "org.telegram.messenger.web",
            "org.thoughtcrime.securesms", // Signal
            "com.viber.voip",
            "com.facebook.orca",          // Messenger
        )

        /** Friendly display names for well-known packages. */
        private val PACKAGE_TO_LABEL = mapOf(
            "com.whatsapp"                  to "WhatsApp",
            "com.whatsapp.w4b"              to "WhatsApp Business",
            "org.telegram.messenger"        to "Telegram",
            "org.telegram.messenger.web"    to "Telegram",
            "org.thoughtcrime.securesms"    to "Signal",
            "com.viber.voip"                to "Viber",
            "com.facebook.orca"             to "Messenger",
        )
    }
}
