/**
 * NotificationEntity.kt — Room Entity for Local Notification Storage
 *
 * This module defines the data class representing a single notification row
 * in the "notifications" SQLite table managed by Room. Each captured notification
 * from a messaging app is stored as one row with metadata for sync tracking.
 *
 * Fields support the sync workflow:
 * - [synced] flag tracks whether the notification has been uploaded to the backend
 * - [createdAt] timestamp enables age-based cleanup of old synced records
 */
package com.palmrag.db

// Room annotation to mark this class as a database entity (table)
import androidx.room.Entity
// Room annotation to designate the primary key column
import androidx.room.PrimaryKey

/**
 * NotificationEntity — Data class representing a single row in the "notifications" table.
 *
 * Stores a captured notification from a messaging app along with sync tracking metadata.
 * Inserted by [NotificationListener] when a notification is captured, queried by
 * [NotificationSyncWorker] for batch upload, and cleaned up after successful sync.
 *
 * @property id Auto-generated primary key (Long); uniquely identifies each notification row
 * @property packageName The Android package name of the source app (e.g., "com.whatsapp")
 * @property title The notification title (e.g., sender name or group name)
 * @property text The notification body text (full message content or big text)
 * @property timestamp Unix timestamp in milliseconds when the notification was posted by the system
 * @property synced Boolean flag indicating whether this notification has been uploaded to the backend
 * @property createdAt Unix timestamp in milliseconds when this row was inserted into the local DB
 */
@Entity(tableName = "notifications")  // Maps this data class to the "notifications" SQLite table
data class NotificationEntity(
    @PrimaryKey(autoGenerate = true)            // Auto-incrementing primary key managed by Room
    val id: Long = 0,                           // Default 0 tells Room to auto-generate the ID
    val packageName: String,                    // Source app package name (e.g., "org.telegram.messenger")
    val title: String,                          // Notification title text (sender/subject)
    val text: String,                           // Notification body text (message content)
    val timestamp: Long,                        // System post time in Unix milliseconds
    val synced: Boolean = false,                // Sync status: false = pending, true = uploaded to backend
    val createdAt: Long = System.currentTimeMillis()  // Local insertion time for age-based cleanup
)
