package com.palmrag.notificationlistener

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * BootReceiver
 *
 * The Android OS kills all services when the device restarts. This receiver
 * listens for [Intent.ACTION_BOOT_COMPLETED] and prompts the system to rebind
 * to [NotificationForwarderService] by toggling notification listener access.
 *
 * Note: The system automatically re-binds NotificationListenerServices that
 * have been granted permission after a reboot – this receiver simply logs the
 * event so developers can confirm the service restarted.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            Log.i(TAG, "Boot completed – NotificationForwarderService will be rebound by the OS.")
        }
    }

    companion object {
        private const val TAG = "BootReceiver"
    }
}
