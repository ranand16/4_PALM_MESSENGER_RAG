/**
 * AppDatabase.kt — Room Database Singleton
 *
 * This module defines the Room database for local notification storage.
 * It uses the thread-safe double-checked locking singleton pattern to ensure
 * only one database instance exists across the entire application lifecycle.
 *
 * Database name: "palm_rag_db"
 * Entities: [NotificationEntity] (single table: "notifications")
 * Schema version: 1 (no migrations defined; exportSchema disabled)
 */
package com.palmrag.db

// Android Context for accessing application resources and file system
import android.content.Context
// Room annotation to declare this class as a database holder
import androidx.room.Database
// Room database builder for creating database instances
import androidx.room.Room
// Base class for all Room databases
import androidx.room.RoomDatabase

/**
 * AppDatabase — Abstract Room database class providing access to [NotificationDao].
 *
 * Configured with [NotificationEntity] as the single entity (table).
 * Uses version 1 with schema export disabled (no migration support needed yet).
 * Access via [getInstance] to get the thread-safe singleton instance.
 */
@Database(entities = [NotificationEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    /**
     * Returns the [NotificationDao] for performing CRUD operations on the notifications table.
     * Room generates the implementation at compile time via KAPT annotation processing.
     */
    abstract fun notificationDao(): NotificationDao

    /**
     * Companion object implementing the thread-safe singleton pattern for database access.
     * Ensures only one Room database instance is created across all threads and components.
     */
    companion object {
        // Volatile ensures this field is immediately visible to all threads after writes
        @Volatile
        private var INSTANCE: AppDatabase? = null  // Singleton instance holder (null until first access)

        /**
         * Returns the singleton [AppDatabase] instance, creating it if necessary.
         * Uses double-checked locking: first check without synchronization for performance,
         * then synchronized block to prevent race conditions during creation.
         *
         * @param context The application context (used to access the file system for the DB file)
         * @return The singleton [AppDatabase] instance
         */
        fun getInstance(context: Context): AppDatabase {
            // Return existing instance if available (fast path without synchronization)
            return INSTANCE ?: synchronized(this) {
                // Inside synchronized block: build the Room database instance
                val instance = Room.databaseBuilder(
                    context.applicationContext,   // Use application context to prevent Activity leaks
                    AppDatabase::class.java,      // The abstract database class to instantiate
                    "palm_rag_db"                 // SQLite database file name on disk
                ).build()
                // Store the created instance in the volatile singleton holder
                INSTANCE = instance
                // Return the newly created instance
                instance
            }
        }
    }
}
