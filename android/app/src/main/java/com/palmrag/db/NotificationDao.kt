/**
 * NotificationDao.kt — Data Access Object for Notification CRUD Operations
 *
 * This module defines the Room DAO interface for all database operations on the
 * "notifications" table. Supports the sync workflow: insert captured notifications,
 * query unsynced items in batches, mark them as synced after successful API upload,
 * clean up old synced records, and count pending items for UI display.
 *
 * All methods are suspend functions for Kotlin coroutine integration.
 */
package com.palmrag.db

// Room DAO annotation marking this interface for code generation
import androidx.room.Dao
// Room annotation for insert operations
import androidx.room.Insert
// Room annotation for raw SQL queries
import androidx.room.Query

/**
 * NotificationDao — Room Data Access Object for the "notifications" table.
 *
 * Provides methods for the notification sync lifecycle:
 * 1. [insert] — Store a newly captured notification
 * 2. [getUnsynced] — Retrieve unsynced notifications for batch upload
 * 3. [markSynced] — Flag notifications as synced after successful API call
 * 4. [cleanOld] — Delete old synced notifications to free storage
 * 5. [unsyncedCount] — Get count of pending notifications for UI display
 */
@Dao
interface NotificationDao {
    /**
     * Inserts a single [NotificationEntity] into the "notifications" table.
     * Called when a new notification is captured by [NotificationListener].
     *
     * @param notification The notification entity to insert
     */
    @Insert
    suspend fun insert(notification: NotificationEntity)

    /**
     * Retrieves up to 100 unsynced notifications ordered by ID ascending (oldest first).
     * The batch limit of 100 prevents large payloads during API sync.
     *
     * @return List of [NotificationEntity] items where synced == 0 (false)
     */
    @Query("SELECT * FROM notifications WHERE synced = 0 ORDER BY id ASC LIMIT 100")
    suspend fun getUnsynced(): List<NotificationEntity>

    /**
     * Marks a list of notifications as synced (synced = 1) by their IDs.
     * Called after the backend API successfully acknowledges the batch.
     *
     * @param ids List of notification IDs to mark as synced
     */
    @Query("UPDATE notifications SET synced = 1 WHERE id IN (:ids)")
    suspend fun markSynced(ids: List<Long>)

    /**
     * Deletes synced notifications that were created before the given timestamp.
     * Used for data retention cleanup (e.g., removing records older than 7 days).
     * Only deletes already-synced records to prevent data loss.
     *
     * @param before Unix timestamp in milliseconds; records created before this are deleted
     */
    @Query("DELETE FROM notifications WHERE synced = 1 AND createdAt < :before")
    suspend fun cleanOld(before: Long)

    /**
     * Returns the count of unsynced notifications in the database.
     * Used by the Settings UI to display the pending sync count to the user.
     *
     * @return Number of notifications where synced == 0 (not yet uploaded)
     */
    @Query("SELECT COUNT(*) FROM notifications WHERE synced = 0")
    suspend fun unsyncedCount(): Int
}
