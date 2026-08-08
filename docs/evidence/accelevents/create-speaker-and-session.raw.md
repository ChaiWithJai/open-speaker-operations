## Page 1: Create speaker
URL: https://developer.accelevents.com/reference/create-speaker.md

> ## Documentation Index
> 
> Fetch the complete documentation index at: https://developer.accelevents.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Create speaker

Using this API, you can create a new speaker for a particular event.

You need to send `SpeakerDTO` as a request body, which contains information like `firstName`, `lastName`, `email` etc.

If a speaker with the same email already exists you will get the error `4068906`.

This API can be used by authenticated users only, and it will require super admin, event admin, and event staff level access.

Here is the description of response attributes, which returns to the form of JSON.

Attributes

Description

id

Unique speaker ID to identify speaker.

Here is the possible error messages, which return if any condition gets failed or required data is missing for processing.

Error Code

Error Description

400

The request could not be understood by the server due to malformed syntax.

401

You are not authorized to view the resource

403

Accessing the resource you were trying to reach is forbidden.

404

The resource you were trying to reach is not found.

4030201

Not Event Host

4068906

Speaker already exist with same email.

406

More than one user exist with same email

# OpenAPI definition

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
    "/rest/host/event/{eventUrl}/speaker": {
      "post": {
        "summary": "Create speaker",
        "description": "Using this API, you can create a new speaker for a particular event. \n\nYou need to send `SpeakerDTO` as a request body, which contains information like `firstName`, `lastName`, `email` etc.\n\nIf a speaker with the same email already exists you will get the error `4068906`.\n\nThis API can be used by authenticated users only, and it will require super admin, event admin, and event staff level access.",
        "operationId": "create-speaker",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API Authorization Token",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "eventUrl",
            "in": "path",
            "description": "Event url is unique identifier for your event. E.g https://www.accelevents.com/events/demo. Here demo is the event url.",
            "schema": {
              "type": "string"
            },
            "required": true
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "RAW_BODY": {
                    "type": "object",
                    "properties": {
                      "allowAttendeeAccess": {
                        "type": "boolean"
                      },
                      "allowOverrideDetails": {
                        "type": "boolean"
                      },
                      "bio": {
                        "type": "string"
                      },
                      "company": {
                        "type": "string"
                      },
                      "deviceChecked": {
                        "type": "boolean"
                      },
                      "email": {
                        "type": "string"
                      },
                      "firstName": {
                        "type": "string"
                      },
                      "imageUrl": {
                        "type": "string"
                      },
                      "instagram": {
                        "type": "string"
                      },
                      "lastName": {
                        "type": "string"
                      },
                      "linkedIn": {
                        "type": "boolean"
                      },
                      "moderator": {
                        "type": "boolean"
                      },
                      "position": {
                        "type": "number",
                        "format": "double"
                      },
                      "pronouns": {
                        "type": "string"
                      },
                      "showModerator": {
                        "type": "boolean"
                      },
                      "speakerId": {
                        "type": "integer",
                        "format": "int64"
                      },
                      "ticketTypesForSpeaker": {
                        "type": "object",
                        "properties": {
                          "speakerOrder": {
                            "type": "boolean"
                          },
                          "ticketTypeId": {
                            "type": "integer",
                            "format": "int64"
                          },
                          "userId": {
                            "type": "integer",
                            "format": "int64"
                          }
                        }
                      },
                      "title": {
                        "type": "string"
                      },
                      "twitter": {
                        "type": "string"
                      },
                      "userId": {
                        "type": "integer",
                        "format": "int64"
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "12"
                  }
                },
                "schema": {
                  "type": "integer",
                  "example": 12,
                  "default": 0
                }
              }
            }
          },
          "400": {
            "description": "400",
            "content": {
              "application/json": {
                "examples": {
                  "Result": {
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
                }
              }
            }
          }
        },
        "deprecated": false
      }
    }
  },
  "x-readme": {
    "headers": [],
    "explorer-enabled": true,
    "proxy-enabled": true
  },
  "x-readme-fauxas": true
}

```

---

## Page 2: create-session.md
URL: https://developer.accelevents.com/reference/create-session.md

---
updatedAt: 2025-09-01T18:56:20.000Z
---

Fetch the complete documentation index at: https://developer.accelevents.com/llms.txt. Use this file to discover all available pages before exploring further.

# Create Session

Using this API you can create a session for the event. 

We recommend sending at least `title`, `startTime`, and `endTime` fields in the request body to create a session. Apart from that, you can also send other attributes related to the session defined in body parameters.

Using `sessionVisibilityType` you can set the session as private/public. 

If the session is set as private then it will be only visible to attendees who are pre-registered by the event admin. For all other attendees, the session will be hidden.
 
You can not set sessions as private for the In-person event and also for the hybrid event type, you can not set the session as private for the In-person ticket.

Only authorized users can use this API and need the event admin, event staff, and super admin.

Here is the description of response attributes, which returns to the form of JSON.

This API Returns created session ID. which auto generated whenever will create new session.

Here are the possible error messages, which return if any condition fails or required data is missing for processing.

 
 
 
 
 Error Code
 

 
 Error Description
 
 
 

 
 
 
 400
 

 
 The request could not be understood by the server due to malformed syntax.
 
 

 
 
 401
 

 
 You are not authorized to view the resource.
 
 

 
 
 403
 

 
 Accessing the resource you were trying to reach is forbidden.
 
 

 
 
 404
 

 
 The resource you were trying to reach is not found.
 
 
 
 

# OpenAPI definition

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
    "/rest/host/event/{eventUrl}/session": {
      "post": {
        "summary": "Create Session",
        "description": "Using this API you can create a session for the event. \n\nWe recommend sending at least `title`, `startTime`, and `endTime`  fields in the request body to create a session. Apart from that, you can also send other attributes related to the session defined in body parameters.\n\nUsing `sessionVisibilityType` you can set the session as private/public. \n\nIf the session is set as private then it will be only visible to attendees who are pre-registered by the event admin. For all other attendees, the session will be hidden.\n \nYou can not set sessions as private for the In-person event and also for the hybrid event type, you can not set the session as private for the In-person ticket.\n\nOnly authorized users can use this API and need the event admin, event staff, and super admin.",
        "operationId": "create-session",
        "parameters": [
          {
            "name": "Authorization",
            "in": "header",
            "description": "API Authentication Token",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "eventUrl",
            "in": "path",
            "description": "Event url is unique identifier for your event. E.g https://www.accelevents.com/events/demo. Here demo is the event url.",
            "schema": {
              "type": "string"
            },
            "required": true
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "RAW_BODY": {
                    "type": "object",
                    "properties": {
                      "title": {
                        "type": "string",
                        "description": "Title of the session. Only 255 Characters are allowed"
                      },
                      "accelEventsStudio": {
                        "type": "boolean",
                        "description": "Is Stream Provide From accelEventsStudio"
                      },
                      "allowedMinutesToJoinLate": {
                        "type": "integer",
                        "description": "Add Minutes To Allow Late Join in session",
                        "format": "int64"
                      },
                      "assetList": {
                        "type": "object",
                        "description": "List of asset for setting default playback after live stream ends",
                        "properties": {
                          "id": {
                            "type": "integer",
                            "description": "Unique Mux Assets ID",
                            "format": "int64"
                          },
                          "assetId": {
                            "type": "integer",
                            "description": "Asset id for mux",
                            "format": "int64"
                          },
                          "createdAt": {
                            "type": "string",
                            "description": "Creation date of asset",
                            "format": "date"
                          },
                          "createdBy": {
                            "type": "integer",
                            "description": "Created By User ID",
                            "format": "int64"
                          },
                          "defaultPlayback": {
                            "type": "boolean",
                            "description": "Is current playback is default selected"
                          },
                          "duration": {
                            "type": "integer",
                            "description": "Duration of playback asset",
                            "format": "int64"
                          },
                          "fileName": {
                            "type": "string",
                            "description": "File name for download"
                          },
                          "playBackId": {
                            "type": "integer",
                            "description": "Playback id for streaming",
                            "format": "int64"
                          }
                        }
                      },
                      "capacity": {
                        "type": "integer",
                        "description": "Set number for session to allow maximum number of user can join.",
                        "format": "int64"
                      },
                      "chimeConfig": {
                        "type": "object",
                        "description": "Chime Config",
                        "properties": {
                          "disableAttendeesCameraOnEntry": {
                            "type": "boolean",
                            "description": "Disable Attendees Camera on  While  Session Entry"
                          },
                          "muteAttendeesOnEntry": {
                            "type": "boolean",
                            "description": "Mute Attendees on Entry While Session Entry"
                          }
                        }
                      },
                      "closedCaptionHeight": {
                        "type": "integer",
                        "description": "Closed caption height For Session",
                        "default": 0,
                        "format": "int32"
                      },
                      "closedCaptionUrl": {
                        "type": "string",
                        "description": "Closed caption URL For Session"
                      },
                      "currentUserRegisteredEventTicketId": {
                        "type": "array",
                        "description": "Event Ticketing ID that a ticketing holder user registered for a session. Event Ticketing ID generates when we create Ticketing Type.",
                        "items": {
                          "type": "integer",
                          "format": "int64"
                        }
                      },
                      "description": {
                        "type": "string",
                        "description": "Description of the session. It's only 65024 Characters are allowed to add description."
                      },
                      "directVideoAutoStart": {
                        "type": "boolean",
                        "description": "Direct video auto start when enter in session"
                      },
                      "displayDonation": {
                        "type": "boolean",
                        "description": "Is display donation In Session"
                      },
                      "documentKeyValue": {
                        "type": "string",
                        "description": "JSON list of session document key value. Key generate automatically while uploading document and value represent document name.",
                        "format": "json"
                      },
                      "duration": {
                        "type": "integer",
                        "description": "Session time span.",
                        "format": "int64"
                      },
                      "enableChat": {
                        "type": "boolean",
                        "description": "Set chat enabled for session"
                      },
                      "enablePoll": {
                        "type": "boolean",
                        "description": "Set poll enabled for session"
                      },
                      "endTime": {
                        "type": "string",