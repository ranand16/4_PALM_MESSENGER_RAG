package com.palmrag.notificationlistener

import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.text.TextUtils
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

/**
 * MainActivity – the only UI screen.
 *
 * The user enters the backend server URL here and then grants
 * "Notification access" in system Settings. Once both are done the
 * [NotificationForwarderService] will forward every matching notification
 * automatically.
 */
class MainActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)

        val etServerUrl: EditText = findViewById(R.id.etServerUrl)
        val btnSave: Button = findViewById(R.id.btnSave)
        val btnPermission: Button = findViewById(R.id.btnGrantPermission)
        val tvStatus: TextView = findViewById(R.id.tvStatus)

        // Restore saved URL
        etServerUrl.setText(prefs.getString(KEY_SERVER_URL, ""))

        btnSave.setOnClickListener {
            val url = etServerUrl.text.toString().trim().trimEnd('/')
            if (url.isEmpty()) {
                Toast.makeText(this, "Please enter a server URL", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            prefs.edit().putString(KEY_SERVER_URL, url).apply()
            Toast.makeText(this, "Server URL saved", Toast.LENGTH_SHORT).show()
        }

        btnPermission.setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }

        // Update status label every time the activity resumes
        updateStatus(tvStatus)
    }

    override fun onResume() {
        super.onResume()
        val tvStatus: TextView = findViewById(R.id.tvStatus)
        updateStatus(tvStatus)
    }

    private fun updateStatus(tvStatus: TextView) {
        tvStatus.text = if (isNotificationListenerEnabled()) {
            "✅  Notification access granted – service is running"
        } else {
            "⚠️  Notification access NOT granted – tap the button below"
        }
    }

    private fun isNotificationListenerEnabled(): Boolean {
        val flat = Settings.Secure.getString(
            contentResolver,
            "enabled_notification_listeners"
        ) ?: return false
        val cn = ComponentName(this, NotificationForwarderService::class.java)
        return flat.split(":").any { it == cn.flattenToString() }
    }

    companion object {
        const val PREFS_NAME = "palmrag_prefs"
        const val KEY_SERVER_URL = "server_url"
    }
}
