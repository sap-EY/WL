# Wockhardt WhatsApp Bot Context File

Starter context for architecture, schema design, orchestration logic, APIs, and code boilerplates.

## Scope Included
- `registered_users`
- `user_registration`

## Scope Excluded
- Any obsolete/older journey variants
- Media delivery over WhatsApp (attachments are intentionally excluded)

---

## 1) Solution Context

This document captures the latest agreed understanding of the WhatsApp bot journeys for Wockhardt LifeSciences Chat bot.

### Key implementation direction
- **Interakt** will be used as the WhatsApp Business Partner / messaging platform.
- The solution currently supports two business journeys:
  - **Registered Users** (already registered doctors whose data is present in master user table)
  - **User Registration** (new/unregistered doctors)
- For **registered users**, the chat experience is intended to be **free-flow conversational**, similar to AI chat interfaces.
- **All user free-text messages** in the registered-user journey must be sent to the **GenAI layer**.
- The **GenAI layer** will interpret all free-text user inputs and return a structured API response containing the necessary intent / action flags so that the orchestration layer can choose the correct **Interakt API**, **template**, or **session message**.
- All answers delivered over WhatsApp will be **text-only**.
- If the answer requires supporting content such as image, video, document, audio, or any other attachment, the WhatsApp bot will **not** send that attachment directly. Instead, the answer text will include an **app/deep link** provide by **GenAI layer** in the same api response to the query.
- Clicking that link should open the mobile app being developed in parallel. If the app is not installed, the link should redirect the user to the respective app store / play store. The points regarding the genai layer and mobile application are not in our scope of development but it's better for your context.
- Consent decline creates a **soft halt only**. Backend should retain the user record with consent status as **declined** or any alternative flag decided during development, and future re-entry is allowed through a new inbound message.
- The WhatsApp/orchestration layer remains responsible for:
  - webhook processing
  - state/session tracking
  - template/session message dispatch through Interakt
  - fallback messaging
  - registration parsing/validation flow handling for onboarding
  - doctor lookup and first-message routing
  - other whatsapp workflow realted stuff mentioned in detail going forward in this document

---

## 2) High-Level Component View

### Logical components
- **WhatsApp User (Doctor)**
- **Interakt WhatsApp APIs / webhook layer**
- **Orchestration / Middleware Layer**
- **GenAI Layer** (not to be handled by us)
- **RAG Engine / Scientific Query Layer** (not to be handled by us)
- **Registration / Validation Backend**
- **Client Master / Doctor Master / Consent Store / Conversation Store**

### Broad responsibility split

#### Interakt Layer
- send template messages
- send session text messages
- receive user messages via webhook
- deliver outbound statuses / events (depending on integration design)

#### Orchestration Layer
- normalize incoming webhook payloads
- identify active session, journey and step
- resolve first inbound message using phone-number lookup and registration status
- store inbound/outbound messages
- call GenAI for registered-user free-flow chat (genai layer responsibility)
- Geani layer will route scientific queries to RAG through GenAI response decisioning (genai layer responsibility)
- call registration parsing/validation services for onboarding flow
- select proper Interakt API / message type based on business decision and genai api reponse
- manage retries, fallbacks, session state, and consent status transitions

#### GenAI Layer (not to be developed by us)
- receive free-text conversational input from registered users
- maintain / consume relevant chat context
- infer user intent
- determine whether the query is:
  - **non-scientific / conversational**
  - **scientific / enterprise-data dependent**
- if non-scientific, return simple text conversation reply
- if scientific, activate / orchestrate RAG-backed answer generation
- return structured response payload with flags that inform orchestration what to send next
  - conversational answer
  - scientific answer
  - hotline intent
  - fallback intent
  - optional app/deep-link in scientific text answer when additional material must be consumed outside WhatsApp

#### Registration Backend
- create internal user record for new users in the master user table
- send the WhatsApp Flow registration template for new doctors
- parse submitted WhatsApp Flow form responses
- update doctor registration record
- mark registration success / failure / escalation state

---

## 3) Common Design Principles
- **Interakt is the messaging gateway** for WhatsApp send/receive operations.
- **Template messages** are used for business-initiated steps where required.
- **Session messages** are used for follow-up, acknowledgements, responses, and fallback messaging where applicable.
- **Registered user journey is free-flow** and should not depend on rigid button-driven Q&A.
- **All free-text from registered users goes to GenAI**; no hardcoded keyword-bypass logic should be implemented in the WhatsApp layer for user free text.
- **GenAI must return structured metadata/flags in their API josn response**, not only raw natural-language text.
- **All WhatsApp answer delivery is text-only**. No WhatsApp media/doc/audio/image/video attachment will be sent by the bot.
- **If supporting content is needed, GenAI should include an app/deep-link in the answer text.**
- **Registration flow is state-driven and deterministic** once the backend identifies whether the user is new or already registered.
- **For any first inbound free-text message, the first resolution step is phone-number lookup in the doctor table.**
- **Consent decline is reversible via future re-entry**; the system may resend the consent template on future user interaction.

---

## 4) Global Free-Text Resolution Logic

This logic applies to the **inbound free-text message** from a user when the system needs to determine whether the user belongs to the **registered_users** journey or the **user_registration** journey.

### Trigger cases
This resolver must run when Interakt webhook receives any free-text user message such as:
- `REGISTER_WL` from QR code / click-to-chat entry
- any other user free text message

### Step 1 — Lookup phone-number in doctor table
On receiving the inbound free-text message, the orchestration layer must first check whether the user phone-number exists in the application `doctor` table.

### Resolution cases

#### Case A — Phone-number not found in doctor table
- create a new shell user record in the doctor table
- initiate **user_registration** journey
- send the `user_registration_v1` WhatsApp Flow template
- user submits registration details inside the WhatsApp Flow form
- on successful form parse/update, mark registration completed
- immediately emit the registration-completed acknowledgement followed by the registered-users consent template

#### Case B — Phone-number found in doctor table
- check whether the user has already been onboarded into the WhatsApp registered-user journey
- if **not onboarded**, send the **consent + welcome/start chat flow** immediately
- if **already onboarded**, route directly into the registered-user chat handling flow

---

## 5) Journey 1 — Registered Users

### 5.1 Purpose
This journey is for **already registered doctors** whose details already or now after registration exist in the doctor table. The objective is to enable:
- consent capture
- AI-assisted free-flow question answering using GenAI/RAG layer built on client knowledge base
- hotline support access
- follow-up conversational continuity just like any other ai chat bot

This journey is intentionally **free-flow chat first**, while still using templates and buttons where useful for consent, satisfaction capture, and hotline access.

### 5.2 Entry Triggers
The registered-users journey can begin via:
- direct first-message routing for a known registered user
- post-registration completion transition from the `user_registration` journey

### 5.3 Step 0 — Welcome + Consent Template Message
**Message type:** Template (already created in interakt, we just need to use it via template name. Text and buttons just for refernce)
**Template name:** `doctor_welcome_consent_v1`

**Draft message text:**
```text
Hi Dr. {{1}} 👋

Thank you for choosing Wockhardt Support 🩺

To continue, please choose an option below:
```

**Buttons / options:**
- Let's continue
- No, thanks

### 5.4 If user selects “No, thanks”
**Message type:** Session text message

**Draft acknowledgement text:**
```text
Thank you, {{Doctor Name}}.
We will not continue with support messages at this time.
If you wish to connect with us later, please reach out to us on {{support}}.
```

**Behavioral rule:**
- this is only a **soft halt**
- backend should keep consent status as `DECLINED`
- future re-entry is allowed
- future inbound user message can trigger consent template message again

### 5.5 If user selects “Let's continue”
**Message type:** Session text message

**Draft acknowledgement text:**
```text
Thank you, {{Doctor Name}}.
Your consent has been recorded successfully.
```

**Next action:** Send post-consent welcome / ice-breaker message.

### 5.6 Post-Consent Welcome / Ice-Breaker Message
After consent is accepted, send a simple welcome/ice-breaker session text + button message that invites free-flow chat.

**Message type:** Session text + button message

**Draft text:**
```text
Thank you Dr. {{Doctor Name}},
You can now start asking your product or medical information queries here in chat, and I will assist you with the relevant information.😊
If you need immediate support, you may connect with hotline support.📞
- message must include button:
  - `Call hotline` (if user clicks this button then we send the dedicated hotline template message)
```

### 5.7 User Sends Free-Text Query
Any free-text message from the doctor in the registered-user journey must be sent to GenAI.

Examples:
- scientific/product query
- natural conversation query
- hotline-related request phrased in natural language
- follow-up question

### 5.8 GenAI First-Level Decision Agent (not in our scope of development)
When the query is sent to GenAI, a **decision agent** will first identify the nature of the query:
- whether it requires the **RAG engine model trained on client enterprise data**
- or whether it can be answered by a **simple natural conversation model**

#### Branch A — Non-scientific / conversational query
If the query is **not scientific**:
- GenAI should return a **simple text conversation reply**
- orchestration sends a **simple session text message** to the user
- no special buttons are required for this branch
- user may ask the next free-text query
- the loop continues naturally

#### Branch B — Scientific / enterprise-data dependent query
If the decision model flags the query as **scientific**:
- genai will send a quick api response to our layer notifying us that the user query is scientific, so we first send the user and acknowledgment message to wait for our response. (see point 5.9 below)
- then **RAG engine** will generate the answer
- orchestration sends the scientific answer to the user as **text-only session answer**
- answer message must include 2 buttons:
  - `Satisfied`
  - `Call hotline`
- if supporting material is needed, include **app/deep link** in the text answer instead of sending media

### 5.9 Processing Acknowledgement (for scientific query path)
Before sending the scientific answer, bot may send a short acknowledgement.

**Message type:** Session text message

**Draft text:**
```text
Let me check that for you. Please wait a moment…⏳
```

### 5.10 Scientific Answer Delivery Rule (not in our scope of development)
All answer messages sent on WhatsApp must be **text-only**.
If the answer needs supporting image/video/document/audio or any other sensitive content, that content must **not** be sent over WhatsApp.
Instead, the answer text should contain a **deep link / app link** that opens the mobile app.
If the app is not installed, the link should redirect to the app store / play store.

**Message type:** session text+button message api
**Example scientific answer pattern:**
```text
Here’s the information you requested, {{Doctor Name}}.
For Product X, the recommended dosage schedule is: 1 tablet twice daily after meals for 5 days, or as per the approved prescribing information.
If additional reference material is needed, please open it in the app using this link: {{app_link}}
```

**Buttons attached to scientific answer:**
- Satisfied
- Call hotline

### 5.11 Scientific Answer Post-Response Cases
After the scientific answer message is sent, 3 possible cases exist:

#### Case 1 — User clicks `Satisfied`
- bot sends thank-you acknowledgement
- flow for this response can safely end here
- user may still re-enter later by sending a new free-text message
**Message type:** session text message api
**Draft text:**
```text
Thank you, {{Doctor Name}}.
Glad I could help.
```

#### Case 2 — User clicks `Call hotline`
- bot sends hotline template message (hotline_v1)
- user clicks hotline CTA
- dialer opens and user is shifted to call journey backend-wise

**Hotline acknowledgement text:**
**Message type:** Template (already created in interakt, we just need to use it via template name. Text and buttons just for reference)
**Template name:** `hotline_v1`
```text
Dr. {{1}}, for immediate assistance, please use the button below to call our support team.
```

**CTA:**
- Call

#### Case 3 — User does not click any button and instead sends the next free-text message
- loop continues
- new free-text again goes to GenAI decision agent

### 5.12 Follow-Up Chat Continues Naturally
The doctor may continue asking follow-up questions in the same chat.

**Core rule:**
- Follow-up chat should remain **natural and conversational**.
- The system should maintain context across the recent conversation. For this the genai layer will maintian a hybrid chat history model. (this is out of our development scope and will be done by genai team)
- All such user text continues to route to GenAI.
- Each user message re-enters the same decision loop:
  - non-scientific → simple text conversation reply
  - scientific → ack message + RAG answer with `Satisfied` + `Call hotline` buttons

### 5.13 Registered Users — Fallbacks
**Message type:** session text message api

#### Fallback 1 — Invalid input when bot expects a button response
Applicable when the doctor is expected to select from explicit buttons (for example, consent step or scientific-answer post-response buttons).

**Draft text:**
```text
Sorry, {{Doctor Name}} — I didn’t catch that.
Please choose one of the options given in the previous message.
```

#### Fallback 2 — Empty / unclear / invalid query
Applicable if the user sends blank text, only symbols, unsupported media instead of text, or an unintelligible message.

**Draft text:**
```text
Sorry, {{Doctor Name}} — I couldn’t understand your question.
Please type your query in a little more detail so I can help better.
```

#### Fallback 3 — GenAI / backend / WhatsApp layer failure
Applicable if answer generation fails or the backend cannot process the request.

**Draft text:**
```text
Sorry, {{Doctor Name}}.
I’m unable to fetch the answer right now.
Please try again after some time or use {{support}} for immediate assistance.
```

---

## 6) Journey 2 — User Registration

### 6.1 Purpose
This journey onboards doctors who are not yet fully registered. As of
Phase 7 the registration handshake uses a **WhatsApp Flow form**
delivered through a template message — the bot never asks for free-text
hash-delimited details.

### 6.2 Entry Trigger
The **user_registration** journey starts on the **first inbound
message** from any phone whose `doctor` row is missing. Entry can be:
- offline-QR / click-to-chat with any pre-filled text (e.g. `REGISTER_WL`)
- any free-text first message
- any button reply that the router maps to Case A or Case D

### 6.3 Registration Flow (single path)
1. Bot sends the `user_registration_v1` template. The template carries a
   single "Register Now" CTA that opens a WhatsApp Flow form inside the
   chat. Journey state is parked at `AWAITING_FULL_DETAILS` (semantics:
   "awaiting form submission").
2. User fills the in-app form and taps **Submit**. Interakt posts a
   `message_api_flow_response` webhook whose `data.message.message
   .nfm_reply.response_json` carries one key per field.
3. Backend upserts the doctor row with the submitted values, sets
   `is_profile_complete = true`, transitions to
   `REGISTRATION_COMPLETED`, and emits the success acknowledgement.
4. The backend immediately emits the registration-completed acknowledgement
  followed by the registered-user consent template in the same transition.

The Flow form is validated client-side by WhatsApp itself, so any
parser failure on our end is treated as a malformed payload and the
journey escalates to `ASSISTED_SUPPORT`.

### 6.4 Form Field Schema
Configured in Interakt under flow id `985469590600160`:

| Field        | Required | UI control     | Stored as            |
| ------------ | -------- | -------------- | -------------------- |
| First Name   | yes      | text           | `doctor.first_name`  |
| Last Name    | yes      | text           | `doctor.last_name`   |
| MCI-ID       | no       | text           | `doctor.mci_id`      |
| Speciality   | yes      | multi-select   | `doctor.speciality` (comma-joined) |

`email`, `address`, `city`, `state`, `pincode` are **not** collected by
the form; the backend writes them as `NULL` so the columns remain
available for future re-introduction without a schema change.

Interakt prefixes each response-json key with `screen_<n>_`. The
parser matches keys by **case-insensitive substring** so the screen
layout can evolve inside Interakt without code edits.

### 6.5 Fully Registered User Path
If the lookup shows the doctor is already fully registered:
- do not start registration
- decide whether the user is already onboarded into the registered-user journey
  - if not onboarded → send consent + welcome template
  - if already onboarded → route directly to free-text handling

### 6.6 Registration Template Copy
**Template name:** `user_registration_v1`
**Template type:** Flow template (`is_flow_template = true`)
**Body (illustrative):**
```text
Hello Doctor 👋
Welcome to Wockhardt Support 🩺

Tap "Register Now" to share your details in a quick in-app form.
```
**CTA button:** `Register Now` → opens the Flow form described in §6.4.

### 6.7 Registration Success Acknowledgement
**Message type:** session text
```text
Thank you {{Doctor Name}}.
Your registration has been completed successfully.
```
**Next step:** doctor becomes eligible for the registered-users
journey; the consent template is sent immediately after this acknowledgement.

### 6.8 Assisted Support Fallback
If the form response cannot be parsed (empty payload, missing required
field) the bot transitions to `ASSISTED_SUPPORT` and sends:
```text
Sorry, we could not process your registration.
Please contact {{support}} for assistance.
```

### 6.9 User Registration — Edge Cases
- user sends free text while in `AWAITING_FULL_DETAILS` → bot re-sends
  the `user_registration_v1` template so the user can tap the CTA again
- user submits the form before the journey row exists (Case A race) →
  handler still upserts the profile and completes the journey
- terminal states (`REGISTRATION_COMPLETED`, `ASSISTED_SUPPORT`) are
  no-ops; the router picks a different journey on the next inbound

---

## 7) Registered Users Full Flowchart — Textual Developer-Friendly Version

```text
START
  |
  v
Any free-text input on webhook
  |
  +--> Input may be QR/click-to-chat initiated REGISTER_WL
  |
  +--> Input may be any other free text
  |
  v
Lookup phone-number in doctor table
  |
  +--> [Phone-number not in doctor table]
  |         |
  |         v
  |   Create new DB record and send user registration message
  |         |
  |         v
  |   User submits WhatsApp Flow form
  |         |
  |         v
  |   Parse form and update user details in DB
  |         |
  |         v
  |   Registration completed
  |         |
  |         v
  |   Send registration-completed acknowledgement + consent template
  |
  +--> [Phone-number found]
            |
            v
        Is user already onboarded in WhatsApp journey?
        |
        +--> [No]
        |         |
        |         v
        |   Set first-message-sent / onboard flag true
        |         |
        |         v
        |   Send consent + welcome message to user
        |
        +--> [Yes]
              |
              v
            Send user's free-text message to GenAI layer
                                          |
                                          v
                          GenAI decision agent: is query scientific / requires RAG?
                                          |
                     +--------------------+--------------------+
                     |                                         |
                   [No]                                      [Yes]
                     |                                         |
                     v                                         v
         Send simple text conversational reply      Bot sends acknowledgement asking user to wait
                     |                                         |
                     |                                         v
                     |                            Bot sends RAG/scientific answer message with buttons:
                     |                              - Satisfied
                     |                              - Call hotline
                     |                                         |
                     |                  +----------------------+----------------------+
                     |                  |                      |                      |
                     |                [Satisfied]         [Call hotline]    [User sends next free-text]
                     |                  |                      |                      |
                     |                  v                      v                      |
                     |        Bot sends thank-you      Bot sends hotline             |
                     |        acknowledgement          acknowledgement/template      |
                     |                  |                      |                      |
                     |                  v                      v                      |
                     |          Flow for this reply     User clicks hotline CTA      |
                     |          can safely end          and dialer opens             |
                     |                                                           loop back
                     +------------------------------------------------------------------->

Consent stage:
  After consent template is sent:
    If user accepts consent:
      - acknowledge consent acceptance
      - send post-consent icebreaker/welcome message
      - user can send free-text or use hotline CTA later
    If user declines consent:
      - acknowledge decline
      - set consent status = DECLINED
      - soft halt only
      - future inbound message can resend consent template
```

---

## 8) User Registration Full Flowchart — Textual Developer-Friendly Version

```text
START
  |
  v
User enters via any first inbound message
  |
  v
Lookup phone-number in doctor table
  |
  +--> [Not found]
  |         |
  |         v
  |   (If not found) create new doctor shell row
  |         |
  |         v
  |   Send `user_registration_v1` template (Flow form CTA)
  |         |
  |         v
  |   Journey state = AWAITING_FULL_DETAILS
  |         |
  |         v
  |   User taps "Register Now" and fills the in-app form
  |         |
  |         v
  |   Interakt webhook: type=message_api_flow_response
  |         |
  |         +--> [Parse failure (malformed/empty)]
  |         |         |
  |         |         v
  |         |   Transition to ASSISTED_SUPPORT
  |         |         |
  |         |         v
  |         |   Send "contact support" message and stop
  |         |
  |         +--> [Parse OK]
  |                   |
  |                   v
  |             Upsert doctor row (first_name, last_name, mci_id,
  |             speciality joined; email/address/city/state/pincode = NULL)
  |                   |
  |                   v
  |             is_profile_complete = true
  |                   |
  |                   v
  |             Send registration-success acknowledgement
  |                   |
  |                   v
  |             Send registered-users consent template immediately
  |
  +--> [Found]
            |
            v
      Route to registered-users journey (Journey 1)
```

---

## 9) Context / Memory Strategy (not in our scope of development)
Because the registered-user chat is free-flow, the GenAI layer must support contextual follow-up responses.

### Recommended production-grade approach
Use a **hybrid context model**:
- store full conversation history in backend / conversation store
- for each GenAI call, send:
  - latest few user-bot turns (for example last 3–5 turns)
  - running summary of earlier context
- maintain a **conversation/session ID** per doctor
- define inactivity timeout/session reset rules separately
- ensure GenAI response is structured enough for orchestration to make message/API decisions

### Why this is preferred
- better scalability than sending the entire transcript every time
- lower token cost
- better contextual continuity for follow-up questions
- easier long-term maintainability

---

## 10) Suggested Data / State Concepts for Implementation

### 10.1 Core entities
At minimum, architecture/schema design may require entities similar to:
- `doctor_profile`
- `doctor_registration`
- `doctor_consent`
- `conversation_session`
- `conversation_message`
- `journey_state`
- `outbound_message_log`
- `inbound_webhook_log`
- `genai_interaction_log`
- `template_registry`
- `hotline_config`
- `registration_parse_attempt`
- `master_data_lookup_log`
- `user_registration_status`
- `whatsapp_onboarding_status`

### 10.2 Suggested journey states

#### Registered Users
- `CONSENT_PENDING`
- `CONSENT_DECLINED`
- `CONSENT_ACCEPTED`
- `CHAT_INIT_SENT`
- `AWAITING_FREE_TEXT_QUERY`
- `GENAI_PROCESSING`
- `QUERY_CLASSIFIED_NON_SCIENTIFIC`
- `QUERY_CLASSIFIED_SCIENTIFIC`
- `ANSWER_SENT`
- `ANSWER_ACTION_PENDING`
- `HOTLINE_TEMPLATE_SENT`
- `FALLBACK_SENT`
- `SESSION_ACTIVE`
- `SESSION_ENDED` (if applicable)

#### User Registration
- `REG_INITIATED`
- `AWAITING_FULL_DETAILS` (current implementation: awaiting WhatsApp Flow form submission)
- `REGISTRATION_COMPLETED`
- `ASSISTED_SUPPORT`

### 10.3 Suggested orchestration routing rules

#### Global free-text-message router (this has to be thought carefully to get the most optimized solution with minimal db or cache lookups to get lowest possible latency)
- if this is the user's inbound free-text message or no active journey/session exists:
  - lookup phone-number in doctor table
  - determine whether user is new or known
  - determine whether known user is already onboarded in WhatsApp journey
  - route to `user_registration` or `registered_users` accordingly

#### For Registered Users
- if active journey is `registered_users` and input is free text:
  - persist inbound message
  - send to GenAI with context
  - consume structured GenAI response
  - if query classified non-scientific:
    - send simple text conversational reply
  - if query classified scientific:
    - optionally send processing acknowledgement
    - send text-only scientific answer with `Satisfied` + `Call hotline` buttons
  - if hotline intent selected/clicked:
    - send hotline template/CTA

#### For User Registration
- if active state = `AWAITING_FULL_DETAILS`:
  - wait for a WhatsApp Flow form response
  - if user sends free text instead, re-send the `user_registration_v1` template
- if a Flow form response arrives:
  - parse form fields and upsert doctor profile
  - send registration-completed acknowledgement followed by consent template
- otherwise:
  - send suitable fallback / context reset message

---

## 11) GenAI API Contract — Starter Suggestion (NOT FINAL)
This section is not final, but useful as Claude starter context.

### Suggested request payload shape (to be finalized during actual development)
```json
{
  "doctor_id": "...",
  "conversation_id": "...",
  "journey": "registered_users",
  "current_state": "AWAITING_FREE_TEXT_QUERY",
  "user_message": "...",
  "recent_turns": [],
  "summary_context": "...",
  "channel": "whatsapp",
  "locale": "en"
}
```

### Suggested response payload shape (to be finalized during actual development)
```json
{
  "success": true,
  "intent": "answer | hotline | fallback",
  "query_nature": "non_scientific | scientific",
  "response_type": "text | template",
  "answer_text": "...",
  "app_link": "...",
  "template_name": "hotline_v1",
  "flags": {
    "send_processing_message": false,
    "end_session": false,
    "requires_hotline": false,
    "requires_template": false,
    "show_answer_buttons": false,
    "use_rag": false
  },
  "meta": {
    "confidence": 0.0,
    "reason": "..."
  }
}
```

### Behavioral rules for response payload
- if `query_nature = non_scientific`, orchestration should send simple conversational text reply and continue loop
- if `query_nature = scientific`, orchestration should send scientific answer text-only with `Satisfied` + `Call hotline` buttons
- if `app_link` is present, include it inside the answer text
- if `intent = hotline`, send hotline template/CTA

---

## 12) Interakt Integration Notes
This project will use **Interakt** as the WhatsApp partner.

### Practical implication
The orchestration layer should be designed in a provider-adapter style so that:
- message send functions are abstracted
- template messages will be pre configured in Interakt and only placeholder inputs will be passed in them
- template send and session send are configurable
- webhook normalization is centralized
- provider-specific details do not leak all over business logic

### Suggested adapter responsibilities
- send template
- send text session message
- send text session message with buttons
- send CTA-enabled template where supported
- parse inbound webhook payload to common internal format
- log outbound response IDs and statuses

---

## 13) Open Questions / TODOs
These are still worth clarifying during implementation planning:
- What is the exact final shape of the GenAI response contract?
- How many previous turns will be sent to GenAI?
- What are the final hotline hours and support contact values? (to be kept configurable via .env file)

---

## 14) Quick Summary

### Registered Users
- first-message-triggered consent + welcome flow
- consent accept/decline handling
- decline is a soft halt with future re-entry allowed
- all free-text goes to GenAI
- GenAI first decides whether query is scientific or non-scientific
- non-scientific query → simple text conversation reply
- scientific query → RAG text-only answer with 2 buttons: `Satisfied`, `Call hotline`
- if supporting content is needed, answer contains deep/app link
- user may continue follow-up free-flow chat indefinitely

### User Registration
- entry can happen from `REGISTER_WL` or any other free-text input
- first step is always phone-number lookup in the doctor table
- new user receives the `user_registration_v1` Flow template
- user submits First Name, Last Name, optional MCI-ID, and Speciality in the in-app form
- backend parses the `message_api_flow_response` event and `nfm_reply.response_json` body
- on Submit, backend upserts the profile, marks registration complete, and sends the registered-users consent template

### Rate limiting
The orchestrator does **not** enforce a client-side request-per-second
cap. Interakt is the source of truth for throughput; if the API
returns HTTP `429 Too Many Requests` the client treats it as a
transient error and retries with tenacity-driven exponential backoff.
No Redis token bucket is used.
---
happens from any first inbound message when the doctor row is missing
- bot sends `user_registration_v1` Flow template (single CTA opens an
  in-app form)
- form collects First Name (req), Last Name (req), MCI-ID (opt),
  Speciality (req multi-select)
- on Submit, backend upserts the profile (email / address / city /
  state / pincode stored as NULL), marks registration complete, and
  triggers the registered-users consent template
- malformed payload escalates straight to assisted support
