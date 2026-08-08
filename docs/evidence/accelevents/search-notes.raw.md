# Web Search Results for "Accelevents API create speaker session endpoint reference"

## 1. Create Session
URL: https://developer.accelevents.com/reference/create-session

Here is the description of response attributes, which returns to the form of JSON.
...
This API Returns created session ID. which auto generated whenever will create new session.
...
Event url is unique identifier for your event. E.g https://www.accelevents.com/events/demo. Here demo is the event url.
...
RAW_BODY
...
RAW_BODY object
...
Defaults to application/json
...
Generated from available response content types
...
application/jsontext/plain
...
`application/json``text/plain`
...
Click`Try It!` to start a request and see the response here! Or choose an example:

## 2. Create speaker
URL: https://developer.accelevents.com/reference/create-speaker

Here is the description of response attributes, which returns to the form of JSON.
...
| Attributes | Description |
| --- | --- |
| id | Unique speaker ID to identify speaker. |
...
| Error Code | Error Description |
| --- | --- |
| 400 | The request could not be understood by the server due to malformed syntax. |
| 401 | You are not authorized to view the resource |
| 403 | Accessing the resource you were trying to reach is forbidden. |
| 404 | The resource you were trying to reach is not found. |
| 4030201 | Not Event Host |
| 4068906 | Speaker already exist with same email. |
| 406 | More than one user exist with same email |
...
Event url is unique identifier for your event. E.g https://www.accelevents.com/events/demo. Here demo is the event url.
...
Click`Try It!` to start a request and see the response here! Or choose an example:

## 3. 
URL: https://developer.accelevents.com/reference/get-all-speakers-with-associated-session

# Get all speakers with associated session details
...
This API allows you to retrieve all the speakers for an event along with their session details. To access this API, you will need to provide the API key. For instructions on how to obtain the API key, please visit the following link: https://developer.accelevents.com/docs/getting-started.
...
# OpenAPI definition
...
```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "accelevents",
    "version": "1.0"
  },
  "servers": [
    {
      "url": "https://api.accelevents.com"
    }
  ],
  "components": {
    "securitySchemes": {
      "sec0": {
        "type": "apiKey",
        "in": "header",
        "name": "Key"
      }
    }
  },
  "security": [
    {
      "sec0": []
    }
  ],
  "paths": {
    "/rest/host/event/{eventUrl}/speaker/speakerWithSessions": {
      "get": {
        "summary": "Get all speakers with associated session details",
        "description": "This API allows you to retrieve all the speakers for an event along with their session details. To access this API, you will need to provide the API key. For instructions on how to obtain the API key, please visit the following link: https://developer.accelevents.com/docs/getting-started.",
        "operationId": "get-all-speakers-with-associated-session",
        "parameters": [
          {
            "name": "eventUrl",
            "in": "path",
            "description": "Event url is unique identifier for your event. E.g https://www.accelevents.com/events/demo. Here demo is the event url.",
            "schema": {
              "type": "string"
            },
            "required": true
          },
          {
            "name": "Key",
            "in": "header",
            "schema": {
              "type": "string",
              "default": "Api Key string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
           ...

## 4. Reference
URL: https://developer.accelevents.com/reference
Published: 2021-01-20T00:00:00.000Z

For AI agents: visit https://developer.accelevents.com/llms.txt for an index of all pages formatted in Markdown and endpoints in OpenAPI.
...
[**Guides](/docs)[**API Reference](/reference)
...
v1.0
...
redirect_uri=/reference
...
/docs)
...
**API Reference
[Log In](/login?redirect_uri=/reference)

## 5. Get session detail
URL: https://developer.accelevents.com/reference/get-session-by-id

Here is the description of response attributes, which returns to the form of JSON.
...
| Attributes | Description |
| --- | --- |
| accelEventsStudio | Identify if session stream provider is accelevents studio, then it's true. If session stream provider is accelevents RTMP, it's false. |
...
| format | It's returns the session format. Can set when create session. There are seven type of session can create that contains MAIN_STAGE, BREAKOUT_SESSION, MEET_UP, WORKSHOP, EXPO, BREAK, OTHER. |
...
| location | It's contains location of session. |
...
| sessionId | The sessionId represents the unique ID of each session. It will be generated automatically when a new session is created. |
...
| speakerList | It's returns the list of speakers that associated with session. It's contains speaker details like speakerId, firatName, lastName, photoUrl and other. |
...
| startTime | It contains the session's starting time in the yyyy/MM/dd HH:mm format. |
...
| streamProvider | It's identify session stream provider, it can be ACCELEVENTS, WISTIA, YOUTUBE, VIMEO, FACEBOOK, ZOOM, DIRECT_UPLOAD. |
| streamUrl | It's a session stream endpoint. |
| tags | It's contains tags for session. |
| title | It contains the title of the session. |
| tracks | It contains the tracks details like ID, name, colour, description and position. It will filter session from all session. |
...
Event url is unique identifier for your event. E.g https://www.accelevents.com/events/demo. Here demo is the event url.
...
Session ID is unique identifier for your session.

## 6. Get speakers list
URL: https://developer.accelevents.com/reference/get-all-speaker

Get speakers list
...
Here is the description of response attributes, which returns to the form of JSON.
...
| Attributes | Description |
| --- | --- |
| speakerId | Unique ID of speaker. |
| pronouns | It's contain speaker pronouns like HE/HIS. |
| title | It's contain speaker title. |
| firstName | Represent speaker first name. |
| lastName | Represent speaker last name. |
| email | Represent speaker email ID. |
| sessionDTO | It's contain details of speaker session. |
| userId | It's contain speaker user ID. |
| allowOverrideDetails | Check if speaker to allow overriding their details. |
| imageUrl | It's contain speaker image URL. |
| company | It's contain speaker company name. |
| bio | It's contains speaker bio. |
| linkedIn | It's contain speaker LinkedIn URL. |
| twitter | It's contain speaker twitter URL. |
| instagram | It's contain speaker instagram URL. |
| position | It's contain speaker position as it's showing accordingly. Position value will be 1000,2000 and 3000 and so on. |
...
Event url is unique identifier for your event. E.g https://www.accelevents.com/events/demo. Here demo is the event url.
...
Get filter speaker records according to search value passing in request

## 7. Display/Portal Speaker API
URL: https://developer.accelevents.com/reference/displayportal-speaker-api

Display/Portal Speaker API
...
Display/Portal Speaker API
...
For AI agents: visit https://developer.accelevents.com/llms.txt for an index of all pages formatted in Markdown and endpoints in OpenAPI.
...
[**Guides](/docs)[**API Reference](/reference)
...
[Log In](/login?redirect_uri=/reference/displayportal-speaker-api)[![Production](https://files.readme.io/426d531-small-dark_fill_icon.png)](/docs)
...
**API Reference
[Log In](/login?redirect_uri=/reference/displayportal-speaker-api)
...
Display/Portal Speaker API
# Display/Portal Speaker API

## 8. Get all sessions for display and portal page
URL: https://developer.accelevents.com/reference/get-all-sessions-for-display-and-portal-page

| Attributes | Description |
| --- | --- |
| sessionId | The sessionId represents the unique ID of each session. It will be generated automatically when a new session is created. |
| title | It contains the title of the session. |
| startTime
...
It contains the session's starting time in the yyyy/MM/dd HH:mm format. |
| endTime | It contains the session's end time in the yyyy/MM/dd HH:mm format. |
...
allowed to add description
...
| format | It's returns the session format. Can set when create session. There are seven type of session can create that contains MAIN_STAGE, BREAKOUT_SESSION, MEET_UP, WORKSHOP, EXPO, BREAK, OTHER |
...
| speakerList | It's returns the list of speakers that associated with session. It's contains speaker details like speakerId, firatName, lastName, photoUrl and other. |
...
| streamProvider | It's identify
...
stream provider, it can be ACCELEVENTS, WISTIA, YOUTUBE, VIMEO, FACEBOOK, ZOOM, DIRECT_UPLOAD. |
...
| streamUrl | It's a session stream endpoint. |
...
Event url is unique identifier for your event. E.g https://www.accelevents.com/events/demo. Here 'demo' is the event url.
