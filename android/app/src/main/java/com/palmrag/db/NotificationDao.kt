package com.palmrag.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query

@Dao
interface NotificationDao {
    @Insert
    suspend fun insert(notification: NotificationEntity)

    @Query("SELECT * FROM notifications WHERE synced = 0 ORDER BY id ASC LIMIT 100")
    suspend fun getUnsynced(): List<NotificationEntity>

    @Query("UPDATE notifications SET synced = 1 WHERE id IN (:ids)")
    suspend fun markSynced(ids: List<Long>)

    @Query("DELETE FROM notifications WHERE synced = 1 AND createdAt < :before")
    suspend fun cleanOld(before: Long)

    @Query("SELECT COUNT(*) FROM notifications WHERE synced = 0")
    suspend fun unsyncedCount(): Int
}
