package com.palmrag.ui

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.palmrag.R
import com.palmrag.db.AppDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class SettingsActivity : AppCompatActivity() {

    private lateinit var etBackendUrl: EditText
    private lateinit var etApiKey: EditText
    private lateinit var tvStatus: TextView
    private lateinit var btnSave: Button
    private lateinit var btnGrantAccess: Button
    private lateinit var tvPendingCount: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        etBackendUrl = findViewById(R.id.et_backend_url)
        etApiKey = findViewById(R.id.et_api_key)
        tvStatus = findViewById(R.id.tv_status)
        btnSave = findViewById(R.id.btn_save)
        btnGrantAccess = findViewById(R.id.btn_grant_access)
        tvPendingCount = findViewById(R.id.tv_pending_count)

        loadSettings()
        updateStatus()

        btnSave.setOnClickListener { saveSettings() }
        btnGrantAccess.setOnClickListener { openNotificationAccess() }
    }

    override fun onResume() {
        super.onResume()
        updateStatus()
        updatePendingCount()
    }

    private fun loadSettings() {
        val prefs = getSharedPreferences("palm_rag_prefs", MODE_PRIVATE)
        etBackendUrl.setText(prefs.getString("backend_url", "http://192.168.1.100:8000"))
        etApiKey.setText(prefs.getString("api_key", ""))
    }

    private fun saveSettings() {
        val url = etBackendUrl.text.toString().trim()
        val key = etApiKey.text.toString().trim()

        if (url.isBlank()) {
            etBackendUrl.error = "Required"
            return
        }
        if (key.isBlank()) {
            etApiKey.error = "Required"
            return
        }

        getSharedPreferences("palm_rag_prefs", MODE_PRIVATE)
            .edit()
            .putString("backend_url", url)
            .putString("api_key", key)
            .apply()

        Toast.makeText(this, "Settings saved", Toast.LENGTH_SHORT).show()
    }

    private fun openNotificationAccess() {
        startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
    }

    private fun updateStatus() {
        val enabled = isNotificationListenerEnabled()
        tvStatus.text = if (enabled) {
            "Notification access: GRANTED"
        } else {
            "Notification access: NOT GRANTED"
        }
    }

    private fun isNotificationListenerEnabled(): Boolean {
        val flat = Settings.Secure.getString(contentResolver, "enabled_notification_listeners")
        val componentName = ComponentName(this, "com.palmrag.NotificationListener")
        return flat?.contains(componentName.flattenToString()) == true
    }

    private fun updatePendingCount() {
        CoroutineScope(Dispatchers.IO).launch {
            val count = AppDatabase.getInstance(applicationContext)
                .notificationDao().unsyncedCount()
            withContext(Dispatchers.Main) {
                tvPendingCount.text = "Pending sync: $count notifications"
            }
        }
    }
}
