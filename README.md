# WikiScraper

This project was created due to a couple use cases I had for obtaining specific
structured information from various sets of wiki pages.

## Goals

Given a wiki (not just Wikipedia) and a set of instructions that outline the
required data, get the data and save it in a format that is consumable by some
other process.  The data can then be used in another application, put into a
database, etc.

To start, this utility will be built with only my initial use case in mind, as
I would like to use this in another project I'm working on.  Over time, it will
be extended to be more general-purpose to facilitate other needs.

### Initial Version

My initial goal is to get information about all endpoints in the
[Destiny Service][0] from the [BungieNetPlatform Wikia site][1].  Required
details for each endpoint include:
- name
- accessibility
- method
- URI
- summary
- path params
- query params
- POST body data
- example request
- example response
- link to Wikia page

This information will help to build a Clojure wrapper around the Bungie.net
REST API.

### Process

1. Parse config file
2. Obtain Wiki markup for each page of interest
3. For each page, parse the markup and extract the required information
4. Save the extracted data to a file

Config file should contain:
- Wiki's base URL
- "selector" for relevant pages (e.g. a category name)
- list of mappings from Wikitext object to a piece of data we need

[0]: http://bungienetplatform.wikia.com/wiki/Category:DestinyService
[1]: http://bungienetplatform.wikia.com/
