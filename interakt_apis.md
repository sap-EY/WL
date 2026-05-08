# Interakt API documentation link:
https://documenter.getpostman.com/view/14760594/2sA2r7zibM#d2d4775c-28f6-47c4-b13b-846422831ce3


# Send Session Message APIs

  ## Send Text Message API

  ### Example Request:

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = json.dumps({
    "userId": "",
    "fullPhoneNumber": "PHONE_NUMBER",
    "callbackData": "some_callback_data",
    "type": "Text",
    "data": {
      "message": "This msg is sent via API"
    }
  })
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response:

  ```json
  {
    "result": true,
    "message": "Message queued for sending via Interakt. Check webhook for delivery status",
    "id": "d58aeff7-a81c-47a7-9b67-f381e13f6c4e"
  }
  ```


  ## Send Audio Message API

  ### Example Request:

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = json.dumps({
    "fullPhoneNumber": "PHONE_NUMBER",
    "callbackData": "some_callback_data",
    "type": "Audio",
    "data": {
      "message": "This is a test",
      "mediaUrl": "MEDIA_URL",
      "fileName": "Test"
    }
  })
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response:

  ```json
  {
    "result": true,
    "message": "Message queued for sending via Interakt. Check webhook for delivery status",
    "id": "d58aeff7-a81c-47a7-9b67-f381e13f6c4e"
  }
  ```


  ## Send Image Message API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = json.dumps({
    "fullPhoneNumber": "PHONE_NUMBER",
    "callbackData": "some_callback_data",
    "type": "Image",
    "data": {
      "message": "This is a test",
      "mediaUrl": "MEDIA_URL"
    }
  })
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message queued for sending via Interakt. Check webhook for delivery status",
    "id": "078fedfa-d3bd-4b6b-b555-ddc10d1f309c"
  }
  ```


  ## Send Document Message API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = json.dumps({
    "fullPhoneNumber": "PHONE_NUMBER",
    "callbackData": "some_callback_data",
    "type": "Document",
    "data": {
      "message": "This is a test",
      "mediaUrl": "MEDIA_URL"
    }
  })
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message queued for sending via Interakt. Check webhook for delivery status",
    "id": "cc311ce6-4a31-4b50-b9e9-186357cd6fdf"
  }
  ```


  ## Send Video Message API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = json.dumps({
    "fullPhoneNumber": "PHONE_NUMBER",
    "callbackData": "some_callback_data",
    "type": "Video",
    "data": {
      "message": "This is a test",
      "mediaUrl": "MEDIA_URL",
      "fileName": "Test"
    }
  })
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message queued for sending via Interakt. Check webhook for delivery status",
    "id": "cc311ce6-4a31-4b50-b9e9-186357cd6fdf"
  }
  ```


  ## Send Button Message API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = json.dumps({
    "fullPhoneNumber": "PHONE_NUMBER",
    "callbackData": "some_callback_data",
    "type": "InteractiveButton",
    "data": {
      "message": {
        "type": "button",
        "body": {
          "text": "Hello, please give your feedback."
        },
        "action": {
          "buttons": [
            {
              "type": "reply",
              "reply": {
                "id": "id1",
                "title": "Ok"
              }
            },
            {
              "type": "reply",
              "reply": {
                "id": "id2",
                "title": "Good"
              }
            },
            {
              "type": "reply",
              "reply": {
                "id": "id3",
                "title": "Bad"
              }
            }
          ]
        }
      }
    }
  })
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message queued for sending via Interakt. Check webhook for delivery status",
    "id": "8a35b1e1-fac5-49b4-84d8-526eaa4c4d77"
  }
  ```


  ## Send List Message API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = json.dumps({
    "fullPhoneNumber": "PHONE_NUMBER",
    "callbackData": "some_callback_data",
    "type": "InteractiveList",
    "data": {
      "message": {
        "type": "list",
        "body": {
          "text": "Check out our top product collections below!"
        },
        "action": {
          "button": "View Collections",
          "sections": [
            {
              "title": "service",
              "rows": [
                {
                  "id": "unique_id1",
                  "title": "All products",
                  "description": "hello"
                }
              ]
            }
          ]
        }
      }
    }
  })
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message queued for sending via Interakt. Check webhook for delivery status",
    "id": "8a35b1e1-fac5-49b4-84d8-526eaa4c4d77"
  }
  ```


  ## Send Sticker Message API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = json.dumps({
    "fullPhoneNumber": "PHONE_NUMBER",
    "callbackData": "some_callback_data",
    "type": "Sticker",
    "data": {
      "mediaUrl": "https://img-06.stickers.cloud/packs/5df297e3-a7f0-44e0-a6d1-43bdb09b793c/webp/8709a42d-0579-4314-b659-9c2cdb979305.webp"
    }
  })
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message queued for sending via Interakt. Check webhook for delivery status",
    "id": "c1db48d6-c615-45ce-8ac2-4d878d73f6aa"
  }
  ```



# Send Template Message APIs
  API keys description:

  countryCode - Country code of the user’s phone (required field)

  phoneNumber - User’s phone number, make sure it does not contain country code or “0” (zero) in beginning of the   number (required field)

  fullPhoneNumber - User’s full phone number along with country code. This fields is optional. You can pass either fullPhoneNumber OR countryCode + phoneNumber. Both are NOT allowed

  callbackData - If you want to store any message level attributes, then you can use the callback_data parameter in the string format to send additional data. This will be returned to you in the corresponding webhooks. We will send an id in response to your API call. This id can be stored for future reference. This id will be referred to when webhooks are returned later. (optional string field with max length 512)

  type - Type of message to be sent; Supported Values: Template (required field)

  template -

  name - Make sure that the template was created in Interakt. The template name to be used is the code name of the template. You will find the code name on the 'info icon' beside the template name in https://app.interakt.ai/templates/list.OR, if you want to use a template which was created by you in Facebook Business Manager, please click on Sync in https://app.interakt.ai/templates/list and after Sync is completed you will see the template appear in the list. (required field)

  languageCode - Language code should match the language in which you had created the template. you can find all language codes here: https://developers.facebook.com/docs/whatsapp/api/messages/message-templates/ (required field)

  template_category (optional): If template_category is set to utility, the message will be sent only if the current category of the template is Utility. If the template’s current category is not Utility, the API request will fail and return an error response indicating a template category mismatch.

  Note - This is useful to ensure that template recategorisation by Meta doesn't cause unintended issues. Meta often recategorises Utility templates to Marketing. Charges for Marketing templates are 5x-6x of Utility & the delivery rate is generally 50%-70%.

  fileName: applicable when document header is used for the document's file name (optional field)

  headerValues - It can hold an array of strings and is used if header type is text & there is a variable in it OR if header type is media(document, image, etc) then used for putting the url for the header's media file (optional field)

  bodyValues - It can hold an array of strings and is used for value of variables in body text (optional field)

  buttonValues - Used in case there are any dynamic URL in the buttons (optional field). It is an object with key as button index in template (starting from 0) and it's value as an array of string for variables in the button. Example: "buttonValues" : { "0" : ["12344"]}If the template has 2 buttons with the first being a contact number, and second being any text with dynamic value - Then the above example would look like "buttonValues" : { "1" : ["12344"]}

  carouselCards - Used in case you want to send a carousel template message. when crafting the API request for each card, the structure for "carouselCards" attribute (headerValues, bodyValues, buttonValues) remains as it is as mentioned earlier in their respective API keys description. Example request here

  ## Send-Templates-NoHeader API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = {
      "fullPhoneNumber": "919999999999", // Optional, Either fullPhoneNumber or phoneNumber + CountryCode is required
      "campaignId" : "YOUR_CAMPAIGN_ID", // Not Mandatory
      "template_category" :"utility",
      "callbackData": "some text here",
      "type": "Template",
      "template": {
          "name": "template_name_here",
          "languageCode": "en",
          "bodyValues": [
              "body_variable_value_1",
              "body_variable_value_n"
          ]
      }
  }
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message created successfully",
    "id": "8d620ba1-640f-42ee-a8dd-15363422144b"
  }
  ```


  ## Send-Template-Text Header with Variable API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = {
      "countryCode": "+91",
      "phoneNumber": "9999999999",
      "fullPhoneNumber": "919999999999", // Optional, Either fullPhoneNumber or phoneNumber + CountryCode is required
      "campaignId" : "YOUR_CAMPAIGN_ID", // Not Mandatory
      "template_category" :"utility",
      "callbackData": "some text here",
      "type": "Template",
      "template": {
          "name": "template_name_here",
          "languageCode": "en",
          "headerValues": [
              "header_variable_value"
          ],
          "bodyValues": [
              "body_variable_value_1",
              "body_variable_value_n"
          ]
      }
  }
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message created successfully",
    "id": "96f0b7a2-6d4c-4983-99c6-eaf7591a5a56"
  }
  ```


  ## Send-Template-Document-Header API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = {
      "countryCode": "+91",
      "phoneNumber": "9999999999",
      "fullPhoneNumber": "919999999999", // Optional, Either fullPhoneNumber or phoneNumber + CountryCode is required
      "campaignId" : "YOUR_CAMPAIGN_ID", // Not Mandatory
      "template_category" :"utility",
      "callbackData": "some text here",
      "type": "Template",
      "template": {
          "name": "template_name_here",
          "languageCode": "en",
          "headerValues": [
              "media_url_here"
          ],
          "fileName": "file_name.pdf",
          "bodyValues": [
              "body_variable_value"
          ]
      }
  }
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message created successfully",
    "id": "36e7d39e-9e3b-4fe6-b21a-abec53ea021e"
  }
  ```


  ## Send-Template-Image-Header API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = {
      "countryCode": "+91",
      "phoneNumber": "9999999999",
      "fullPhoneNumber": "919999999999", // Optional, Either fullPhoneNumber or phoneNumber + CountryCode is required
      "campaignId" : "YOUR_CAMPAIGN_ID", // Not Mandatory
      "template_category" :"utility",
      "callbackData": "some text here",
      "type": "Template",
      "template": {
          "name": "template_name_here",
          "languageCode": "bg",
          "headerValues": [
              "media_url_here"
          ],
          "bodyValues": [
              "body_variable_value"
          ]
      }
  }
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message created successfully",
    "id": "b90f02bd-1316-49ce-b5d0-f6be14fce2b8"
  }
  ```


  ## Send-Authentication-Template API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = {
      "countryCode": "+91",
      "phoneNumber": "9028883545",
      "callbackData": "some text here",
      "type": "Template",
      "template": {
          "name": "itk_auth_one_tap",
          "languageCode": "en",
          "bodyValues": [
              "LIPSUM"
          ],
          "buttonValues": {
              "0": [
                  "LIPSUM"
              ]
          }
      }
  }
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message created successfully",
    "id": "b90f02bd-1316-49ce-b5d0-f6be14fce2b8"
  }
  ```


  ## Send-Template-Dynamic-CTA API

  ### Example Request

  ```
  url = "https://api.interakt.ai/v1/public/message/"

  method = POST

  payload = {
      "countryCode": "+91",
      "phoneNumber": "9999999999",
      "fullPhoneNumber": "919999999999", // Optional, Either fullPhoneNumber or phoneNumber + CountryCode is required
      "campaignId" : "YOUR_CAMPAIGN_ID", // Not Mandatory
      "template_category" :"utility",
      "callbackData": "some text here",
      "type": "Template",
      "template": {
          "name": "template_name_here",
          "languageCode": "en",
          "bodyValues": [
              "body_variable_value_1",
              "body_variable_value_2"
          ],
          "buttonValues": {
              "1": [
                  "button_variable_value"
              ]
          }
      }
  }
  headers = {
    'Authorization': 'Basic {{YOUR_API_KEY}}',
    'Content-Type': 'application/json'
  }
  ```

  ### Example Response

  ```json
  {
    "result": true,
    "message": "Message created successfully",
    "id": "2d14b3d9-5dc2-4a76-b139-7394cac5888f"
  }
  ```
