package com.palmrag.api

import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST

data class NotificationDTO(
    val package_name: String,
    val title: String,
    val text: String,
    val timestamp: Long,
    val device_id: String
)

data class NotificationBatch(
    val notifications: List<NotificationDTO>,
    val device_id: String
)

data class IngestResponse(
    val stored: Int,
    val received: Int
)

interface NotificationApi {
    @POST("/api/notifications")
    suspend fun sendNotifications(
        @Header("X-API-Key") apiKey: String,
        @Body batch: NotificationBatch
    ): Response<IngestResponse>
}

object ApiClient {
    private var retrofit: Retrofit? = null
    private var currentBaseUrl: String? = null

    fun getApi(baseUrl: String): NotificationApi {
        if (retrofit == null || currentBaseUrl != baseUrl) {
            currentBaseUrl = baseUrl
            retrofit = Retrofit.Builder()
                .baseUrl(baseUrl)
                .addConverterFactory(GsonConverterFactory.create())
                .build()
        }
        return retrofit!!.create(NotificationApi::class.java)
    }
}
