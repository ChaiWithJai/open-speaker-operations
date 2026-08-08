## Page 1: update-speaker.md
URL: https://developer.accelevents.com/reference/update-speaker.md

---
updatedAt: 2025-06-12T20:22:35.000Z
---

Fetch the complete documentation index at: https://developer.accelevents.com/llms.txt. Use this file to discover all available pages before exploring further.

# Update speaker

Using this API, you can update speakers' details. 

You have to send the speakers' id as `id` (session ID) and the event URL in the path parameter. Also, you need to pass speakerDTO as the body parameter.

This API can be used by authenticated users only, and it will require super admin, event admin, and event staff level access.

Here is the description of response attributes, which returns to the form of JSON.

This API Returns a void response with 200 status if the API executed successfully.

Here are the possible error messages, which return if any condition gets failed or required data is missing for processing.

 
 
 
 
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
 
 

 
 
 4030201
 

 
 Not Event Host
 
 

 
 
 4090121
 

 
 User has already logged in at website, Can't change email now!
 
 

 
 
 404801
 

 
 Speaker not found!
 
 

 
 
 4068906
 

 
 Speaker already exist with same email
 
 

 
 
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
    "/rest/host/event/{eventUrl}/speaker/{id}": {
      "put": {
        "summary": "Update speaker",
        "description": "Using this API, you can update speakers' details. \n\nYou have to send the speakers' id as `id` (session ID) and the event URL  in the path parameter. Also, you need to pass speakerDTO as the body parameter.\n\nThis API can be used by authenticated users only, and it will require super admin, event admin, and event staff level access.",
        "operationId": "update-speaker",
        "parameters": [
          {
            "name": "id",
            "in": "path",
            "description": "Unique speaker ID",
            "schema": {
              "type": "integer",
              "format": "int32"
            },
            "required": true
          },
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
                  "speakerDTO": {
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
                    "value": "{}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {}
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

## Page 2: get-all-speakers.md
URL: https://developer.accelevents.com/reference/get-all-speakers.md

---
updatedAt: 2025-06-12T20:22:32.000Z
---

Fetch the complete documentation index at: https://developer.accelevents.com/llms.txt. Use this file to discover all available pages before exploring further.

# Get speakers list

Using this API, you can get speakers list for a particular event. 

You have to send `eventId` as a query parameter. Apart from that, you can pass `searchString`, `page`, `size` & `expand` as query parameters for pagination & filter data.

This API can be used by authenticated users only, and it will require super admin, event admin, event staff level access.

Here is the description of response attributes, which returns to the form of JSON.

 
 
 
 
 Attributes
 

 
 Description
 
 
 

 
 
 
 **recordsTotal** 
 

 
 It's contain total count of speakers
 
 

 
 
 **recordsFiltered** 
 

 
 It's contain filtered records count of speakers
 
 

 
 
 **data** 
 

 
 It's contain each speaker's details.
 
 

 
 
 **speakerId** 
 

 
 Unique ID of speaker.
 
 

 
 
 **title** 
 

 
 It's contain speaker title.
 
 

 
 
 **pronouns** 
 

 
 It's contain speaker pronouns like HE/HIS.
 
 

 
 
 **firstName** 
 

 
 Represent speaker first name.
 
 

 
 
 **lastName** 
 

 
 Represent speaker last name.
 
 

 
 
 **email** 
 

 
 Represent speaker email ID.
 
 

 
 
 **sessionDTO** 
 

 
 It's contain details of speaker session.
 
 

 
 
 **userId** 
 

 
 It's contain speaker user ID.
 
 

 
 
 **imageUrl** 
 

 
 It's contain speaker image URL.
 
 

 
 
 **company** 
 

 
 It's contain speaker company name.
 
 

 
 
 **bio** 
 

 
 It's contains speaker bio.
 
 

 
 
 **linkedIn** 
 

 
 It's contain speaker LinkedIn URL.
 
 

 
 
 **twitter** 
 

 
 It's contain speaker twitter URL.
 
 

 
 
 **instagram** 
 

 
 It's contain speaker instagram URL.
 
 

 
 
 **position** 
 

 
 It's contain speaker position as it's showing accordingly. Position value will be 1000,2000 and 3000 and so on.
 
 

 
 
 **moderator** 
 

 
 It returns a boolean value if the speaker is moderator in session it will return true or else false.
 
 

 
 
 **ticketTypesForSpeaker** 
 

 
 It's contains details of ticket types of speaker to allow attendee access to speaker
 
 

 
 
 **showModerator** 
 

 
 Return true if allow showing moderator into speaker list or else it will return false and will not showing to speaker list.
 
 

 
 
 **deviceChecked** 
 

 
 Check status of speaker run device checker or not.
 
 

 
 
 **loggedInAtVEH** 
 

 
 Check speaker previous checked in for Virtual Event Hub.
 
 

 
 
 **allowAttendeeAccess** 
 

 
 Check If allow to access attendee.
 
 

 
 
 **allowOverrideDetails**
 

 
 Check if speaker to allow overriding their details.
 
 
 
 

Here are the possible error messages, which return if any condition gets failed or required data is missing for processing.

 
 
 
 
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
 
 

 
 
 4040200
 

 
 Event Not Found
 
 
 
 

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
      "get": {
        "summary": "Get speakers list",
        "description": "Using this API, you can get speakers list for a particular event. \n\nYou have to send `eventId` as a query parameter. Apart from that, you can pass `searchString`, `page`, `size` & `expand` as query parameters for pagination & filter data.\n\nThis API can be used by authenticated users only, and it will require super admin, event admin, event staff level access.",
        "operationId": "get-all-speakers",
        "parameters": [
          {
            "name": "searchString",
            "in": "query",
            "description": "Get filter session records according to search value passing in request",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "eventId",
            "in": "query",
            "description": "Unique event Id used to get speakers related to event.",
            "schema": {
              "type": "integer",
              "format": "int32"
            }
          },
          {
            "name": "page",
            "in": "query",
            "description": "Pages are zero indexed, thus providing 0 for page will return the first page.",
            "schema": {
              "type": "integer",
              "format": "int32"
            }
          },
          {
            "name": "size",
            "in": "query",
            "description": "Size will returns number of records when call api default will returns 10 records",
            "schema": {
              "type": "integer",
              "format": "int32"
            }
          },
          {
            "name": "expand",
            "in": "query",
            "description": "Expands Get Records accordingly we are passing in request param in expand value as comma separated like : TAG,TRACK,SPEAKER,currentUserRegisteredEventTicketId",
            "required": true,
            "schema": {
              "type": "string"
            }
          },
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
          },
          {
            "name": "accept",
            "in": "header",
            "schema": {
              "type": "string",
              "default": "application/json"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "200",
            "content": {
              "text/plain": {
                "examples": {
                  "Result": {
                    "value": "{\n  \"recordsTotal\": 1,\n  \"recordsFiltered\": 1,\n  \"data\": [\n    {\n      \"speakerId\": 4516,\n      \"title\": \"QA\",\n      \"pronouns\": \"Spekaer\",\n      \"firstName\": \"Test Dhara2\",\n      \"lastName\": \"L2\",\n      \"email\": \"test@url2.com\",\n      \"sessionDTO\": null,\n      \"userId\": 10078,\n      \"imageUrl\": \"\",\n      \"company\": \"Brilworks\",\n      \"bio\": \"Master in SoftwaerSystem\",\n      \"linkedIn\": \"https://www.linkedin.com/\",\n      \"twitter\": \"https://twitter.com/home?lang=en\",\n      \"instagram\": \"https://www.instagram.com/\",\n      \"position\": 1000,\n      \"moderator\": null,\n      \"ticketTypesForSpeaker\": null,\n      \"showModerator\": null,\n      \"deviceChecked\": false,\n      \"loggedInAtVEH\": false,\n      \"allowAttendeeAccess\": null,\n      \"allowOverrideDetails\": false\n    }\n  ],\n  \"error\": null\n}"
                  }
                },
                "schema": {
                  "type": "object",
                  "properties": {
                    "recordsTotal": {
                      "type": "integer",
                      "example": 1,
                      "default": 0
                    },
                    "recordsFiltered": {
                      "type": "integer",
                      "example": 1,
                      "default": 0
                    },
                    "data": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "speakerId": {
                            "type": "integer",
                            "example": 4516,
                            "default": 0
                          },
                          "title": {
                            "type": "string",
                            "example": "QA"
                          },
                          "pronouns": {
                            "type": "string",
                            "example": "Spekaer"
                          },
                          "firstName": {
                            "type": "string",
                            "example": "Test Dhara2"
                          },
                          "lastName": {
                            "type": "string",
                            "example": "L2"
                          },
                          "email": {
                            "type": "string",
                            "example": "test@url2.com"
                          },
                          "sessionDTO": {},
                          "userId": {
                            "type": "integer",
                            "example": 10078,
                            "default": 0
                          },
                          "imageUrl": {
                            "type": "string",
                            "example": ""
                          },
                          "company": {
                            "type": "string",
                            "example": "Brilworks"
                          },
                          "bio": {
                            "type": "string",
                            "example": "Master in SoftwaerSystem"