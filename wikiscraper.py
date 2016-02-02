#!/usr/bin/env python

import hashlib
import json
import mwparserfromhell
import pprint
import re
import sys
import urllib2
import yaml

# http://stackoverflow.com/a/14692747
def rget(dataDict, mapList):
    return reduce(lambda d, k: d[k], mapList, dataDict)

def stripSyntaxHighlighter(text):
    text = text.replace("<syntaxhighlight lang=\"javascript\">", "")
    text = text.replace("</syntaxhighlight>", "")

    return text

def hashPageText(data):
    data["textHash"] = hashlib.sha256(data["text"].encode("utf-8")).hexdigest()
    del data["text"]

def combineNamesAndDescriptions(d, varType):
    nameField = varType + "VariableNames"
    descField = varType + "VariableDescriptions"
    finalField = varType + "Variables"
    if nameField in d and descField in d:
        if len(d[nameField]) == 0 or len(d[descField]) == 0:
            print "Empty array found!"
        elif len(d[nameField]) != len(d[descField]):
            print "Unmatched pairs!"
        else:
            pairs = {}
            pattern = re.compile("\[\[([A-Za-z]*)\|([A-Za-z]*)\]\]")
            for i in xrange(0, len(d[nameField])):
                key = d[nameField][i]
                val = d[descField][i]
                m = pattern.match(key)
                if m:
                    pairs[m.group(2)] = val + " (See %s Wikia page for more details.)" % m.group(1)
                else:
                    pairs[key] = val
            d[finalField] = pairs
            del d[nameField]
            del d[descField]
    elif nameField in d:
        print "Only names found!"
    elif descField in d:
        print "Only descriptions found!"

def cleanExampleRequest(data):
    if "httpMethod" in data and "exampleRequest" in data and data["httpMethod"] == "post":
        try:
            req = json.loads(data["exampleRequest"].split("\n", 1)[1])
            data["exampleRequest"] = json.dumps(req)
        except ValueError as ve:
            print "Error decoding JSON for exampleRequest in " + data["name"]

# GetPublicXurVendor has blocks for "When Xur is/isn't available."
def cleanExampleResponse(data):
    if data["name"] == "GetPublicXurVendor":
        res = data["exampleResponse"].replace("When Xur isn't available.", "")
        responses = res.split("When Xur is available.")
        try:
            data["exampleResponses"] = [
                json.dumps(json.loads(responses[1])),
                json.dumps(json.loads(responses[0]))
            ]
            del data["exampleResponse"]
        except ValueError as ve:
            print "Error decoding JSON for exampleResponses in GetPublicXurVendor"
            print responses
    elif "exampleResponse" in data:
        res = data["exampleResponse"]
        phrases = [
            "Please note: This response has been truncated for easier viewing.",
            "This response has been truncated to make it easier to see the full structure.",
            "// Note this is an associative array"
        ]
        for phrase in phrases:
            res = res.replace(phrase, "")
        try:
            res = json.loads(res)
            data["exampleResponses"] = [json.dumps(res)]
            del data["exampleResponse"]
        except ValueError as ve:
            print "Error decoding JSON for exampleResponse in " + data["name"]
            print res

# TODO: This is VERY specific
def performExtractions(pageData):
    text = rget(pageData, ["revisions", 0, "*"])
    # TODO: Make this configurable
    text = stripSyntaxHighlighter(text)
    wikicode = mwparserfromhell.parse(text)
    template = wikicode.filter_templates()[0]
    # Perform extractions
    data = {}
    for ext in conf["extractions"]:
        sel = ext["selector"]
        if sel["type"] == "pageData":
            data[rget(ext, ["target", "name"])] = pageData[sel["value"]]
        elif sel["type"] == "pageText":
            data[rget(ext, ["target", "name"])] = rget(pageData, ["revisions", 0, "*"])
        elif sel["type"] == "templateVariable":
            if template.has(sel["value"]):
                var = template.get(sel["value"]).value.strip()
                if var != "":
                    data[ext["target"]["name"]] = var
        elif sel["type"] == "collectedTemplateVariables":
            for i in xrange(sel["rangeStart"], sel["rangeEnd"]+1):
                varName = "{0}{1}".format(sel["value"], i)
                targetName = ext["target"]["name"]
                if template.has(varName):
                    if targetName not in data:
                        data[targetName] = []
                    data[targetName].append(template.get(varName).value.strip())

    # TODO: Make this configurable too
    hashPageText(data)
    combineNamesAndDescriptions(data, "path")
    combineNamesAndDescriptions(data, "queryString")
    combineNamesAndDescriptions(data, "jsonBody")
    cleanExampleRequest(data)
    cleanExampleResponse(data)

    return data

# TODO: Fucking awful
def handleResponse(response, baseUrl, extractedData=[]):
    for pageId, pageData in rget(response, ["query", "pages"]).iteritems():
        extractedData.append(performExtractions(pageData))

    if "query-continue" in response:
        continueParam = response["query-continue"].values()[0]
        url = baseUrl + "&%s=%s" % (continueParam.keys()[0], continueParam.values()[0])
        nextResponse = json.loads(urllib2.urlopen(url).read())
        extractedData = handleResponse(nextResponse, baseUrl, extractedData)

    return extractedData


# TODO: Check out argparse
# Make sure a config file's name was passed in, then load it
if len(sys.argv) == 2:
    # TODO: Verify file exists
    conf = yaml.load(file(sys.argv[1], "r"))
else:
    # TODO: Print usage
    print "No file specified!"

# Get data
# TODO: Support looping and paging
url = "{0}/api.php?action=query&format=json&prop=revisions&rvprop=content".format(conf["baseUrl"])
# TODO: Support other types of selectors
selType = rget(conf, ["pageSelector", "type"])
selVal = rget(conf, ["pageSelector", "value"])
if selType == "pageid":
    url = url + "&pageids={0}".format(selVal)
elif selType == "category":
    url = url + "&generator=categorymembers&gcmtitle=Category:{0}".format(selVal)
# TODO: Make this waaayyyyy safer
# TODO: http://docs.python-requests.org/en/latest/
response = json.loads(urllib2.urlopen(url).read())

# Extract data
extractedData = handleResponse(response, url)

# TODO: This is also terrible
yaml.safe_dump(extractedData, file(conf["outputFilename"], "w"))
yaml.dump(extractedData, file(conf["outputFilename"].replace(".yml", "-loadable.yml"), "w"))
