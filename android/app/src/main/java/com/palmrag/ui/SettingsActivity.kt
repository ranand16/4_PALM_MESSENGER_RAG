/**
 * SettingsActivity.kt — Main Configuration UI Activity
 *
 * This module provides the primary user interface for the PALM RAG app.
 * It allows users to:
 * - Enter and save the backend server URL and API key
 * - Grant notification access permission (required for NotificationListener)
 * - View the current notification access status
 * - See the count of pending (unsynced) notifications
 *
 * Settings are persisted in SharedPreferences under "palm_rag_prefs".
 * This activity is registered as the MAIN/LAUNCHER activity in the manifest.
 */
package com.palmrag.ui

// Android ComponentName for constructing fully-qualified service names
import android.content.ComponentName
// Android Context for SharedPreferences access
import android.content.Context
// Android Intent for launching system settings screens
import android.content.Intent
// Android Bundle for saving/restoring activity instance state
import android.os.Bundle
// Android Settings class for accessing system notification listener settings
import android.provider.Settings
// Android Button widget for user interactions
import android.widget.Button
// Android EditText widget for text input fields
import android.widget.EditText
// Android TextView widget for displaying text labels
import android.widget.TextView
// Android Toast for displaying brief feedback messages
import android.widget.Toast
// AndroidX AppCompatActivity base class with Material theme support
import androidx.appcompat.app.AppCompatActivity
// App resource references (R.layout, R.id)
import com.palmrag.R
// Room database singleton for querying pending notification count
import com.palmrag.db.AppDatabase
// Kotlin coroutine scope for launching async operations
import kotlinx.coroutines.CoroutineScope
// IO dispatcher for database queries on background thread
import kotlinx.coroutines.Dispatchers
// Coroutine builder for launching non-blocking async tasks
import kotlinx.coroutines.launch
// Dispatcher switch for updating UI from a background coroutine
import kotlinx.coroutines.withContext

/**
 * SettingsActivity — The main configuration screen for the PALM RAG Android app.
 *
 * Extends [AppCompatActivity] for Material Design theme support.
 * Provides input fields for backend URL and API key, a button to grant
 * notification access, status display, and pending sync count.
 */
class SettingsActivity : AppCompatActivity() {

    // EditText for entering the backend server URL (e.g., "http://192.168.1.100:8000")
    private lateinit var etBackendUrl: EditText
    // EditText for entering the API key used to authenticate with the backend
    private lateinit var etApiKey: EditText
    // TextView displaying the current notification access permission status
    private lateinit var tvStatus: TextView
    // Button that saves the backend URL and API key to SharedPreferences
    private lateinit var btnSave: Button
    // Button that opens the system notification access settings screen
    private lateinit var btnGrantAccess: Button
    // TextView displaying the count of unsynced notifications pending upload
    private lateinit var tvPendingCount: TextView

    /**
     * Called when the activity is first created.
     * Inflates the layout, binds view references, loads saved settings,
     * updates the notification access status, and sets up click listeners.
     *
     * @param savedInstanceState Bundle containing previously saved instance state (or null)
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        // Call the parent class onCreate to perform default Activity initialization
        super.onCreate(savedInstanceState)
        // Inflate and set the activity_settings.xml layout as this activity's content view
        setContentView(R.layout.activity_settings)

        // Bind view references to their corresponding XML layout elements by ID
        etBackendUrl = findViewById(R.id.et_backend_url)       // Backend URL input field
        etApiKey = findViewById(R.id.et_api_key)               // API key input field
        tvStatus = findViewById(R.id.tv_status)                // Notification access status label
        btnSave = findViewById(R.id.btn_save)                  // Save settings button
        btnGrantAccess = findViewById(R.id.btn_grant_access)   // Grant notification access button
        tvPendingCount = findViewById(R.id.tv_pending_count)   // Pending sync count label

        // Load previously saved backend URL and API key from SharedPreferences into the fields
        loadSettings()
        // Check and display whether notification access permission is currently granted
        updateStatus()

        // Set click listener on the save button to persist settings to SharedPreferences
        btnSave.setOnClickListener { saveSettings() }
        // Set click listener on the grant access button to open system notification settings
        btnGrantAccess.setOnClickListener { openNotificationAccess() }
    }

    /**
     * Called when the activity resumes from the background (e.g., returning from
     * system settings). Refreshes the notification access status and pending count
     * since the user may have changed permissions while away.
     */
    override fun onResume() {
        // Call parent onResume to resume the activity lifecycle
        super.onResume()
        // Refresh the notification access status (may have changed in system settings)
        updateStatus()
        // Refresh the pending notification count from the database
        updatePendingCount()
    }

    /**
     * Loads saved backend URL and API key from SharedPreferences into the input fields.
     * Uses "http://192.168.1.100:8000" as the default URL if none is saved.
     */
    private fun loadSettings() {
        // Access the app's SharedPreferences store
        val prefs = getSharedPreferences("palm_rag_prefs", MODE_PRIVATE)
        // Set the backend URL field to the saved value, or default to local network address
        etBackendUrl.setText(prefs.getString("backend_url", "http://192.168.1.100:8000"))
        // Set the API key field to the saved value, or empty string if not configured
        etApiKey.setText(prefs.getString("api_key", ""))
    }

    /**
     * Validates and saves the backend URL and API key to SharedPreferences.
     * Shows validation errors on blank fields and a Toast confirmation on success.
     */
    private fun saveSettings() {
        // Read and trim whitespace from the backend URL input
        val url = etBackendUrl.text.toString().trim()
        // Read and trim whitespace from the API key input
        val key = etApiKey.text.toString().trim()

        // Validate that the backend URL is not empty
        if (url.isBlank()) {
            etBackendUrl.error = "Required"  // Show inline error on the URL field
            return                            // Stop saving if validation fails
        }
        // Validate that the API key is not empty
        if (key.isBlank()) {
            etApiKey.error = "Required"  // Show inline error on the API key field
            return                        // Stop saving if validation fails
        }

        // Save both values to SharedPreferences using apply() for async disk write
        getSharedPreferences("palm_rag_prefs", MODE_PRIVATE)
            .edit()
            .putString("backend_url", url)   // Persist the backend URL
            .putString("api_key", key)        // Persist the API key
            .apply()                          // Write asynchronously to disk

        // Show a brief confirmation Toast to the user
        Toast.makeText(this, "Settings saved", Toast.LENGTH_SHORT).show()
    }

    /**
     * Opens the Android system notification listener settings screen.
     * The user needs to manually enable the PALM RAG notification listener
     * from this system settings page for the app to capture notifications.
     */
    private fun openNotificationAccess() {
        // Launch an intent to the system's notification listener settings screen
        startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
    }

    /**
     * Updates the notification access status TextView to reflect whether
     * the NotificationListener service is currently enabled by the user.
     */
    private fun updateStatus() {
        // Check if the notification listener permission is currently granted
        val enabled = isNotificationListenerEnabled()
        // Update the status text to show GRANTED or NOT GRANTED
        tvStatus.text = if (enabled) {
            "Notification access: GRANTED"      // Permission is enabled
        } else {
            "Notification access: NOT GRANTED"   // Permission is not enabled
        }
    }

    /**
     * Checks whether the NotificationListener service is enabled in Android system settings.
     * Reads the "enabled_notification_listeners" secure setting and checks if our
     * service's ComponentName is present in the colon-separated list.
     *
     * @return true if the NotificationListener is enabled, false otherwise
     */
    private fun isNotificationListenerEnabled(): Boolean {
        // Read the system-level list of enabled notification listener components
        val flat = Settings.Secure.getString(contentResolver, "enabled_notification_listeners")
        // Construct the ComponentName for our NotificationListener service
        val componentName = ComponentName(this, "com.palmrag.NotificationListener")
        // Check if our service's flattened name appears in the enabled list
        return flat?.contains(componentName.flattenToString()) == true
    }

    /**
     * Queries the Room database for the count of unsynced notifications
     * and updates the pending count TextView on the main thread.
     * Uses a coroutine on the IO dispatcher for the database query.
     */
    private fun updatePendingCount() {
        // Launch a coroutine on the IO dispatcher for the database query
        CoroutineScope(Dispatchers.IO).launch {
            // Query the Room database for the number of unsynced notifications
            val count = AppDatabase.getInstance(applicationContext)
                .notificationDao().unsyncedCount()
            // Switch to the Main dispatcher to update the UI safely
            withContext(Dispatchers.Main) {
                // Update the pending count text with the current unsynced notification count
                tvPendingCount.text = "Pending sync: $count notifications"
            }
        }
    }
}
