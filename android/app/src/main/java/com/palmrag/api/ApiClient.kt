/**
 * ApiClient.kt — Retrofit-based HTTP Client for Backend API Communication
 *
 * This module defines the data transfer objects (DTOs) for notification batching,
 * the Retrofit API interface for the backend REST endpoint, and a singleton
 * ApiClient object that manages the Retrofit instance with lazy initialization
 * and base URL change detection.
 *
 * Used by [NotificationSyncWorker] to push captured notifications to the backend.
 */
package com.palmrag.api

// Retrofit Response wrapper for handling HTTP responses
import retrofit2.Response
// Retrofit builder for creating API client instances
import retrofit2.Retrofit
// Gson converter factory for automatic JSON serialization/deserialization
import retrofit2.converter.gson.GsonConverterFactory
// Annotation for HTTP request body
import retrofit2.http.Body
// Annotation for HTTP request header
import retrofit2.http.Header
// Annotation for HTTP POST method
import retrofit2.http.POST

/**
 * Data transfer object representing a single notification to send to the backend.
 *
 * @property package_name The Android package name of the source app (e.g., "com.whatsapp")
 * @property title The notification title (e.g., sender name or chat group name)
 * @property text The notification body text (full message content)
 * @property timestamp The Unix timestamp in milliseconds when the notification was posted
 * @property device_id A unique identifier for the device sending the notification
 */
data class NotificationDTO(
    val package_name: String,   // Source app's Android package name (snake_case for backend JSON)
    val title: String,          // Notification title from the status bar
    val text: String,           // Notification body text or big text content
    val timestamp: Long,        // Unix timestamp in milliseconds when notification was posted
    val device_id: String       // Device identifier (Build.MODEL + Build.ID)
)

/**
 * Data transfer object for sending a batch of notifications to the backend.
 *
 * @property notifications List of [NotificationDTO] items to ingest
 * @property device_id The device ID associated with this batch
 */
data class NotificationBatch(
    val notifications: List<NotificationDTO>,  // List of notification DTOs in this batch
    val device_id: String                       // Device identifier for the entire batch
)

/**
 * Response DTO returned by the backend after ingesting a notification batch.
 *
 * @property stored Number of notifications successfully stored in the vector DB
 * @property received Number of notifications received in the request
 */
data class IngestResponse(
    val stored: Int,    // Count of notifications that were successfully embedded and stored
    val received: Int   // Count of notifications received by the backend in the request
)

/**
 * Retrofit interface defining the backend API endpoints.
 * Each method maps to a specific REST endpoint on the backend server.
 */
interface NotificationApi {
    /**
     * Sends a batch of notifications to the backend for ingestion.
     * Authenticated via the X-API-Key header (constant-time comparison on server).
     *
     * @param apiKey The API key for authentication (sent as X-API-Key header)
     * @param batch The [NotificationBatch] containing notifications to ingest
     * @return [Response] wrapping an [IngestResponse] with stored/received counts
     */
    @POST("/api/notifications")  // Maps to the POST /api/notifications backend endpoint
    suspend fun sendNotifications(
        @Header("X-API-Key") apiKey: String,  // Authentication header for backend API
        @Body batch: NotificationBatch         // JSON request body with notification batch
    ): Response<IngestResponse>
}

/**
 * Singleton object managing the Retrofit HTTP client instance.
 *
 * Provides lazy initialization of the Retrofit instance and automatically
 * rebuilds it if the base URL changes (e.g., user updates the backend URL
 * in settings). This ensures the API client always points to the correct server.
 */
object ApiClient {
    // Cached Retrofit instance; null until first use or after URL change
    private var retrofit: Retrofit? = null
    // The base URL currently configured in the cached Retrofit instance
    private var currentBaseUrl: String? = null

    /**
     * Returns a [NotificationApi] instance configured with the given base URL.
     * Creates a new Retrofit instance if one doesn't exist or if the base URL
     * has changed since the last call (e.g., user updated settings).
     *
     * @param baseUrl The backend server base URL (e.g., "http://192.168.1.100:8000")
     * @return A [NotificationApi] implementation for making API calls
     */
    fun getApi(baseUrl: String): NotificationApi {
        // Check if we need to create or recreate the Retrofit instance
        if (retrofit == null || currentBaseUrl != baseUrl) {
            // Update the tracked base URL to the new value
            currentBaseUrl = baseUrl
            // Build a new Retrofit instance with the updated base URL and Gson converter
            retrofit = Retrofit.Builder()
                .baseUrl(baseUrl)                                    // Set the backend server URL
                .addConverterFactory(GsonConverterFactory.create())  // Add Gson for JSON parsing
                .build()
        }
        // Create and return the NotificationApi interface implementation from Retrofit
        return retrofit!!.create(NotificationApi::class.java)
    }
}
