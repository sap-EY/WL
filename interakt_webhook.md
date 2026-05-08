-> For webhooks of templates sent via APIs, the types will be as follows:

    "message_api_sent"

    "message_api_delivered"

    "message_api_read"

    "message_api_failed"

    "message_api_clicked"

-> For incoming customer message webhooks, the type will be as follows:

    "message_received"

-> Read the data.customer object to see customer’s phone number & the values of all customer attributes stored in Interakt for that particular customer

-> Read the data.message object to identify which message is being referred to

-> Webhook Requirements

    Your webhook should meet the following minimum performance requirements:
        Must be an HTTPS endpoint
        Respond to all webhook events with a 200 OK
        Respond to all webhook events in 3 seconds or less


# Sample Webhook Body (taken from interakt website)

## message_api_sent
(note – data sent in the “traits” object depends on the customer traits present in our Interakt account. The traits given in the example below corresponds to a test account)
```json
{
  "version": "1.0",
  "timestamp": "2022-06-03T05:43:33.237499",
  "type": "message_api_sent",
  "data": {
    "customer": {
      "id": "52918eb3-bd00-4331-a51d-c4dcffee48d6",
      "channel_phone_number": "917003705584",
      "traits": {
        "name": "SKGG",
        "amount": 7000,
        "total_orders_count": 0,
        "last_order_id": null,
        "last_order_name": null,
        "total_spent": "0.00",
        "whatsapp_opted_in": false,
        "created_at": "2021-06-23T06:46:11",
        "User Id": "111",
        "email": "xyz@gmail.com"
      }
    },
    "message": {
      "id": "dfc668a2-c06c-4e9a-a4fd-7b65bc1fdc84",
      "chat_message_type": "PublicApiMessage",
      "channel_failure_reason": null,
      "message_status": "Sent",
      "received_at_utc": "2022-06-03T05:43:33.133000",
      "delivered_at_utc": null,
      "seen_at_utc": null,
      "campaign_id": null,
      "is_template_message": true,
      "raw_template": "{\"id\": \"281a5a78-f2b2-46c9-b9bb-d620d3b2894c\", \"created_at_utc\": \"2022-03-30T07:04:04.078\", \"modified_at_utc\": \"2022-03-31T05:41:09.61\", \"created_by_user_id\": \"37088e03-3633-4aa4-b4d8-99edbc56d4fc\", \"is_deleted\": false, \"name\": \"test_template_lp\", \"language\": \"en\", \"category\": \"ALERT_UPDATE\", \"header_format\": null, \"header\": null, \"header_handle\": null, \"header_handle_file_url\": null, \"header_handle_file_name\": null, \"header_text\": null, \"body\": \"Hi  {{1}} \\nWelcome to interakt, my name is  {{2}} . I hope your 14 day free trial was helpful. For any queries please reach to us.\", \"body_text\": \"[\\\"Clients\\\", \\\"Sender\\\"]\", \"footer\": \"Team interakt\", \"buttons\": \"[{\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Thank you\\\"}, {\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"What is qralink?\\\"}, {\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Speak to an agent\\\"}]\", \"button_text\": null, \"display_name\": \"Test template\", \"organization_id\": \"ba4308f1-a506-44d2-a8c3-17380216cf91\", \"approval_status\": \"APPROVED\", \"wa_template_id\": \"3224400424546364\", \"is_archived\": false}",
      "channel_error_code": null,
      "message_content_type": "Template",
      "media_url": null,
      "message": "[{\"type\": \"body\", \"parameters\": [{\"type\": \"text\", \"text\": \"Saandhy\"}, {\"type\": \"text\", \"text\": \"Varun\"}]}]",
      "meta_data": {
        "source": "PublicInterakt",
        "source_data": {
          "callback_data": "some text here"
        }
      }
    }
  }
}
```


## message_api_delivered
```json
{
  "version": "1.0",
  "timestamp": "2022-06-03T05:43:33.930227",
  "type": "message_api_delivered",
  "data": {
    "customer": {
      "id": "52918eb3-bd00-4331-a51d-c4dcffee48d6",
      "channel_phone_number": "917003705584",
      "traits": {
        "name": "SKGG",
        "amount": 7000,
        "total_orders_count": 0,
        "last_order_id": null,
        "last_order_name": null,
        "total_spent": "0.00",
        "whatsapp_opted_in": false,
        "created_at": "2021-06-23T06:46:11",
        "User Id": "111",
        "email": "xyz@gmail.com"
      }
    },
    "message": {
      "id": "dfc668a2-c06c-4e9a-a4fd-7b65bc1fdc84",
      "chat_message_type": "PublicApiMessage",
      "channel_failure_reason": null,
      "message_status": "Delivered",
      "received_at_utc": "2022-06-03T05:43:33.133000",
      "delivered_at_utc": "2022-06-03T05:43:33.848000",
      "seen_at_utc": null,
      "campaign_id": null,
      "is_template_message": true,
      "raw_template": "{\"id\": \"281a5a78-f2b2-46c9-b9bb-d620d3b2894c\", \"created_at_utc\": \"2022-03-30T07:04:04.078\", \"modified_at_utc\": \"2022-03-31T05:41:09.61\", \"created_by_user_id\": \"37088e03-3633-4aa4-b4d8-99edbc56d4fc\", \"is_deleted\": false, \"name\": \"test_template_lp\", \"language\": \"en\", \"category\": \"ALERT_UPDATE\", \"header_format\": null, \"header\": null, \"header_handle\": null, \"header_handle_file_url\": null, \"header_handle_file_name\": null, \"header_text\": null, \"body\": \"Hi  {{1}} \\nWelcome to interakt, my name is  {{2}} . I hope your 14 day free trial was helpful. For any queries please reach to us.\", \"body_text\": \"[\\\"Clients\\\", \\\"Sender\\\"]\", \"footer\": \"Team interakt\", \"buttons\": \"[{\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Thank you\\\"}, {\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"What is qralink?\\\"}, {\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Speak to an agent\\\"}]\", \"button_text\": null, \"display_name\": \"Test template\", \"organization_id\": \"ba4308f1-a506-44d2-a8c3-17380216cf91\", \"approval_status\": \"APPROVED\", \"wa_template_id\": \"3224400424546364\", \"is_archived\": false}",
      "channel_error_code": null,
      "message_content_type": "Template",
      "media_url": null,
      "message": "[{\"type\": \"body\", \"parameters\": [{\"type\": \"text\", \"text\": \"Saandhy\"}, {\"type\": \"text\", \"text\": \"Varun\"}]}]",
      "meta_data": {
        "source": "PublicInterakt",
        "source_data": {
          "callback_data": "some text here"
        }
      }
    }
  }
}
```


## message_api_read
```json
{
  "version": "1.0",
  "timestamp": "2022-06-03T05:43:33.930227",
  "type": "message_api_read",
  "data": {
    "customer": {
      "id": "52918eb3-bd00-4331-a51d-c4dcffee48d6",
      "channel_phone_number": "917003705584",
      "traits": {
        "name": "SKGG",
        "amount": 7000,
        "total_orders_count": 0,
        "last_order_id": null,
        "last_order_name": null,
        "total_spent": "0.00",
        "whatsapp_opted_in": false,
        "created_at": "2021-06-23T06:46:11",
        "User Id": "111",
        "email": "xyz@gmail.com"
      }
    },
    "message": {
      "id": "dfc668a2-c06c-4e9a-a4fd-7b65bc1fdc84",
      "chat_message_type": "PublicApiMessage",
      "channel_failure_reason": null,
      "message_status": "Read",
      "received_at_utc": "2022-06-03T05:43:33.133000",
      "delivered_at_utc": "2022-06-03T05:43:33.848000",
      "seen_at_utc": "2022-06-03T05:43:34.257000",
      "campaign_id": null,
      "is_template_message": true,
      "raw_template": "{\"id\": \"281a5a78-f2b2-46c9-b9bb-d620d3b2894c\", \"created_at_utc\": \"2022-03-30T07:04:04.078\", \"modified_at_utc\": \"2022-03-31T05:41:09.61\", \"created_by_user_id\": \"37088e03-3633-4aa4-b4d8-99edbc56d4fc\", \"is_deleted\": false, \"name\": \"test_template_lp\", \"language\": \"en\", \"category\": \"ALERT_UPDATE\", \"header_format\": null, \"header\": null, \"header_handle\": null, \"header_handle_file_url\": null, \"header_handle_file_name\": null, \"header_text\": null, \"body\": \"Hi  {{1}} \\nWelcome to interakt, my name is  {{2}} . I hope your 14 day free trial was helpful. For any queries please reach to us.\", \"body_text\": \"[\\\"Clients\\\", \\\"Sender\\\"]\", \"footer\": \"Team interakt\", \"buttons\": \"[{\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Thank you\\\"}, {\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"What is qralink?\\\"}, {\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Speak to an agent\\\"}]\", \"button_text\": null, \"display_name\": \"Test template\", \"organization_id\": \"ba4308f1-a506-44d2-a8c3-17380216cf91\", \"approval_status\": \"APPROVED\", \"wa_template_id\": \"3224400424546364\", \"is_archived\": false}",
      "channel_error_code": null,
      "message_content_type": "Template",
      "media_url": null,
      "message": "[{\"type\": \"body\", \"parameters\": [{\"type\": \"text\", \"text\": \"Saandhy\"}, {\"type\": \"text\", \"text\": \"Varun\"}]}]",
      "meta_data": {
        "source": "PublicInterakt",
        "source_data": {
          "callback_data": "some text here"
        }
      }
    }
  }
}
```


## message_api_failed
```json
{
  "version": "1.0",
  "timestamp": "2022-06-03T05:56:10.699936",
  "type": "message_api_failed",
  "data": {
    "customer": {
      "id": "82a5b5bc-5509-4225-a9e9-bbe4c150516b",
      "channel_phone_number": "919831....",
      "traits": {
        "name": "",
        "whatsapp_opted_in": true
      }
    },
    "message": {
      "id": "80b4b1f1-dc39-46dc-a133-bf09a12c3d4e",
      "chat_message_type": "PublicApiMessage",
      "channel_failure_reason": "Recipient is not a valid WhatsApp user",
      "message_status": "Failed",
      "received_at_utc": "2022-06-03T05:56:10.502000",
      "delivered_at_utc": null,
      "seen_at_utc": null,
      "campaign_id": null,
      "is_template_message": true,
      "raw_template": "{\"id\": \"281a5a78-f2b2-46c9-b9bb-d620d3b2894c\", \"created_at_utc\": \"2022-03-30T07:04:04.078\", \"modified_at_utc\": \"2022-03-31T05:41:09.61\", \"created_by_user_id\": \"37088e03-3633-4aa4-b4d8-99edbc56d4fc\", \"is_deleted\": false, \"name\": \"test_template_lp\", \"language\": \"en\", \"category\": \"ALERT_UPDATE\", \"header_format\": null, \"header\": null, \"header_handle\": null, \"header_handle_file_url\": null, \"header_handle_file_name\": null, \"header_text\": null, \"body\": \"Hi  {{1}} \\nWelcome to interakt, my name is  {{2}} . I hope your 14 day free trial was helpful. For any queries please reach to us.\", \"body_text\": \"[\\\"Clients\\\", \\\"Sender\\\"]\", \"footer\": \"Team interakt\", \"buttons\": \"[{\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Thank you\\\"}, {\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"What is qralink?\\\"}, {\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Speak to an agent\\\"}]\", \"button_text\": null, \"display_name\": \"Test template\", \"organization_id\": \"ba4308f1-a506-44d2-a8c3-17380216cf91\", \"approval_status\": \"APPROVED\", \"wa_template_id\": \"3224400424546364\", \"is_archived\": false}",
      "channel_error_code": "1013",
      "message_content_type": "Template",
      "media_url": null,
      "message": "[{\"type\": \"body\", \"parameters\": [{\"type\": \"text\", \"text\": \"Saandhy\"}, {\"type\": \"text\", \"text\": \"Varun\"}]}]",
      "meta_data": {
        "source": "PublicInterakt",
        "source_data": {
          "callback_data": "some text here"
        }
      }
    }
  }
}
```


## message_api_clicked (Quick Reply Buttons)
```json
{
  "version": "1.0",
  "timestamp": "2024-06-10T08:38:08.837610",
  "type": "message_api_clicked",
  "data": {
    "customer": {
      "id": "fe366bc2-14df-40f3-ab56-20f67f5c6694",
      "channel_phone_number": "917003705584",
      "phone_number": "7003705584",
      "country_code": "+91",
      "traits": {
        "name": "Saandhy Ganeriwala",
        "whatsapp_opted_in": true
      }
    },
    "message": {
      "id": "f6f22110-9eab-4282-9b2c-673c3bbaa0fa",
      "chat_message_type": "PublicApiMessage",
      "channel_failure_reason": null,
      "message_status": "Read",
      "received_at_utc": "2024-06-10T08:37:46.309000",
      "delivered_at_utc": "2024-06-10T08:37:48.149000",
      "seen_at_utc": "2024-06-10T08:38:05.643000",
      "campaign_id": null,
      "is_template_message": true,
      "raw_template": "{\"id\": \"8472d21c-7d9d-40d4-9d36-2616c67a39bd\", \"created_at_utc\": \"2024-02-22T11:46:07.  328\", \"modified_at_utc\": \"2024-06-06T15:40:29.987\", \"created_by_user_id\": \"None\", \"is_deleted\":   false, \"name\": \"looking_for_feedback_23\", \"language\": \"en\", \"category\": \"UTILITY\",   \"sub_category\": null, \"template_category_label\": null, \"header_format\": null, \"header\": null,   \"header_handle\": null, \"header_handle_file_url\": null, \"header_handle_file_name\": null, \"header_text\":   null, \"body\": \"Hey {{1}} \\n\\nThis is {{2}} from Interakt's Product Team. We are looking to improve our   product so that businesses like yours can use & derive more value from Interakt.\\n\\nWe hence have a very   simple question for you - *What can we do to make Interakt more useful for you?*\\n\\nYou can fill the feedback   form, or, schedule a 30 mins meeting with me.\", \"body_text\": \"[\\n    \\\"John\\\",\\n    \\\"Mark\\\"\\n]  \", \"footer\": null, \"buttons\": \"[{\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Fill Feedback   Form\\\"}, {\\\"type\\\": \\\"QUICK_REPLY\\\", \\\"text\\\": \\\"Schedule Meet\\\"}]\", \"button_text\": null, \"allow_category_change\": true, \"limited_time_offer\": null, \"autosubmitted_for\": null, \"display_name\": \"looking_for_feedback_23\", \"organization_id\": \"80a1681a-3fbd-4580-beff-eb93478211a5\", \"approval_status\": \"APPROVED\", \"wa_template_id\": \"1586626795428976\", \"is_archived\": false, \"channel_type\": \"Whatsapp\", \"is_click_tracking_enabled\": false, \"allow_delete\": true, \"rejection_reason\": null, \"carousel_cards\": \"[]\", \"is_carousel\": false, \"is_mpm\": false}",
      "channel_error_code": null,
      "message_content_type": "Template",
      "media_url": null,
      "message": "[{\"type\": \"body\", \"parameters\": [{\"type\": \"text\", \"text\": \"body_variable_value_1\"}, {\"type\": \"text\", \"text\": \"body_variable_value_2\"}]}]",
      "meta_data": {
        "source": "PublicInterakt",
        "source_data": {
          "callback_data": "some text here123"
        },
        "message_cost": {
          "whatsapp_cost": "0.03",
          "interakt_markup": "0.3",
          "actual_message_cost": "0.33"
        },
        "click_type": "QR",
        "button_text": "Fill Feedback Form",
        "button_link": "",
        "click_timestamp": "2024-06-10 08:38:08.635664",
        "button_payload": {
          "payload": {
            "type": "QUICK_REPLY",
            "text": "Fill Feedback Form"
          }
        }
      }
    }
  }
}
```


## message_api_clicked (Call-to-action Buttons)
```json
{
  "version": "1.0",
  "timestamp": "2024-06-10T08:38:08.837610",
  "type": "message_api_clicked",
  "data": {
    "customer": {
      "id": "fe366bc2-14df-40f3-ab56-20f67f5c6694",
      "channel_phone_number": "917003705584",
      "phone_number": "7003705584",
      "country_code": "+91",
      "traits": {
        "name": "Saandhy Ganeriwala",
        "email": "saandhy.ganeriwala+999111@gmail.com",
        "whatsapp_opted_in": true
      }
    },
    "message": {
      "id": "c2e35816-f6cb-4893-8cd5-99d2f6060535",
      "chat_message_type": "PublicApiMessage",
      "channel_failure_reason": null,
      "message_status": "Read",
      "received_at_utc": "2024-06-10T08:47:19.352000",
      "delivered_at_utc": "2024-06-10T08:47:21.123000",
      "seen_at_utc": "2024-06-10T08:47:21.723000",
      "campaign_id": null,
      "is_template_message": true,
      "raw_template": "{\"id\": \"fe9066ad-57a2-4137-ad5d-292b08be1551\", \"created_at_utc\": \"2022-06-09T08:00:26.058\", \"modified_at_utc\": \"2024-06-10T08:46:06.076\", \"created_by_user_id\": \"2f0a1016-0886-4dfb-8681-4c3aed78df8e\", \"is_deleted\": false, \"name\": \"order_shipped_1010123\", \"language\": \"en\", \"category\": \"UTILITY\", \"header_format\": null, \"header\": null, \"header_handle\": null, \"header_handle_file_url\": null, \"header_handle_file_name\": null, \"header_text\": null, \"body\": \"Hi {{1}}, your order is shipped. Please click below to track the order.\", \"body_text\": \"[\\n    \\\"John\\\"\\n]\", \"footer\": null, \"buttons\": \"[{\\\"type\\\":\\\"URL\\\",\\\"text\\\":\\\"Track Order\\\",\\\"url\\\":\\\"https://www.interakt.shop/\\\"}]\", \"button_text\": \"[]\", \"display_name\": \"Order Shipped 1010123\", \"organization_id\": \"80a1681a-3fbd-4580-beff-eb93478211a5\", \"approval_status\": \"APPROVED\", \"wa_template_id\": \"8276292472397006\", \"is_archived\": false, \"template_category_label\": null, \"channel_type\": \"Whatsapp\", \"allow_delete\": true, \"allow_category_change\": true, \"autosubmitted_for\": null, \"rejection_reason\": null, \"is_click_tracking_enabled\": true, \"limited_time_offer\": null, \"sub_category\": null, \"carousel_cards\": \"[]\", \"is_carousel\": false, \"is_mpm\": false}",
      "channel_error_code": null,
      "message_content_type": "Template",
      "media_url": null,
      "message": "[{\"type\": \"body\", \"parameters\": [{\"type\": \"text\", \"text\": \"body_variable_value_1\"}]}, {\"type\": \"button\", \"sub_type\": \"url\", \"index\": 0, \"parameters\": [{\"type\": \"text\", \"text\": \"\"}]}]",
      "meta_data": {
        "source": "PublicInterakt",
        "source_data": {
          "callback_data": "some text here123"
        },
        "message_cost": {
          "whatsapp_cost": "0.03",
          "interakt_markup": "0.3",
          "actual_message_cost": "0.33"
        }
      }
    },
    "event": {
      "callbackData": "some text here123",
      "click_type": "CTA",
      "button_text": "Track Order",
      "button_link": "https://www.interakt.shop/",
      "click_timestamp": "2024-06-10 08:47:26.948896"
    }
  }
}
```


## message_received
```json
{
  "version": "1.0",
  "timestamp": "2022-06-03T05:57:57.496889",
  "type": "message_received",
  "data": {
    "customer": {
      "id": "52918eb3-bd00-4331-a51d-c4dcffee48d6",
      "channel_phone_number": "917003705584",
      "traits": {
        "name": "SKGG",
        "amount": 7000,
        "total_orders_count": 0,
        "last_order_id": null,
        "last_order_name": null,
        "total_spent": "0.00",
        "whatsapp_opted_in": false,
        "created_at": "2021-06-23T06:46:11",
        "User Id": "111",
        "email": "xyz@gmail.com"
      }
    },
    "message": {
      "id": "60076f05-da52-4dd1-b813-36223c1eded7",
      "chat_message_type": "CustomerMessage",
      "channel_failure_reason": null,
      "message_status": "Sent",
      "received_at_utc": "2022-06-03T05:57:57.359000",
      "delivered_at_utc": null,
      "seen_at_utc": null,
      "campaign_id": null,
      "is_template_message": false,
      "raw_template": null,
      "channel_error_code": null,
      "message_content_type": "Text",
      "media_url": null,
      "message": "Thank you",
      "meta_data": {}
    }
  }
}
```
