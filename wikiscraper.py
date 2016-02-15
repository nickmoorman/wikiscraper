#!/usr/bin/env python

import argparse
import copy
import hashlib
import json
import mwparserfromhell
import os.path
import pprint
import re
import requests
import yaml

class WikiScraper:
    """Used to scrape structured data from a set of MediaWiki pages"""

    def __init__(self, configFileName, fromFiles):
        """Set up the scraper"""
        if not configFileName:
            raise ValueError("Must pass in the name of a config file")
        self.configFileName = configFileName
        if os.path.isfile(configFileName):
            with open(configFileName, "r") as configFile:
                self.conf = yaml.load(configFile)
        else:
            raise IOError("Config file %s does not exist" % configFileName)

        self.fromFiles = fromFiles

        # Set up base URL and params for easy access
        self.baseUrl = self.conf["baseUrl"]
        self.baseParams = {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "rvprop": "content"
        }
        selType = rget(self.conf, ["pageSelector", "type"])
        selVal = rget(self.conf, ["pageSelector", "value"])
        # TODO: Support other types of selectors
        if selType == "pageid":
            self.baseParams["pageids"] = selVal
        elif selType == "category":
            self.baseParams.update({
                "generator": "categorymembers",
                "gcmtitle": "Category:%s" % selVal
            })

    def makeRequest(self, extraParams=None, saveUrl=False):
        """Make a MediaWiki API request"""
        params = copy.deepcopy(self.baseParams)
        if extraParams:
            params.update(extraParams)
        response = requests.get(self.baseUrl, params=params)
        if response.status_code == requests.codes.ok:
            rj = response.json()
            if saveUrl:
                rj["metadata"] = {
                    "source": response.url
                }
            return rj
        else:
            response.raise_for_status()

    def getResponseFileName(self, index):
        return self.configFileName.replace(".yml", "-raw-%03d.json" % index)

    def loadResponseFile(self, index):
        responseFileName = self.getResponseFileName(index)
        if os.path.isfile(responseFileName):
            with open(responseFileName, "r") as responseFile:
                return json.load(responseFile)
        else:
            raise IOError("Response file %s does not exist" % responseFileName)

    # TODO: Rip this out and put it in a custom domain module
    def stripSyntaxHighlighter(self, text):
        text = text.replace("<syntaxhighlight lang=\"javascript\">", "")
        text = text.replace("</syntaxhighlight>", "")

        return text

    def hashPageText(self, data):
        data["textHash"] = hashlib.sha256(data["text"].encode("utf-8")).hexdigest()
        del data["text"]

    # TODO: Rip this out and put it in a custom domain module
    def combineNamesAndDescriptions(self, d, varType):
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

    # TODO: Rip this out and put it in a custom domain module
    def cleanExampleRequest(self, data):
        if "httpMethod" in data and "exampleRequest" in data and data["httpMethod"] == "post":
            try:
                req = json.loads(data["exampleRequest"].split("\n", 1)[1])
                data["exampleRequest"] = json.dumps(req)
            except ValueError as ve:
                print "Error decoding JSON for exampleRequest in " + data["name"]

    # TODO: Rip this out and put it in a custom domain module
    # GetPublicXurVendor has blocks for "When Xur is/isn't available."
    def cleanExampleResponse(self, data):
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
                "// Note this is an associative array",
                "Note: Response has been truncated."
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
    def performExtractions(self, pageData):
        text = rget(pageData, ["revisions", 0, "*"])
        # TODO: Make this configurable
        text = self.stripSyntaxHighlighter(text)
        wikicode = mwparserfromhell.parse(text)
        template = wikicode.filter_templates()[0]
        # Perform extractions
        data = {}
        for ext in self.conf["extractions"]:
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
        self.hashPageText(data)
        self.combineNamesAndDescriptions(data, "path")
        self.combineNamesAndDescriptions(data, "queryString")
        self.combineNamesAndDescriptions(data, "jsonBody")
        self.cleanExampleRequest(data)
        self.cleanExampleResponse(data)

        return data

    def saveResponses(self, response=None, responseIndex=0):
        if not response:
            response = self.makeRequest(saveUrl=True)
        nextResponse = None
        if "query-continue" in response:
            continueParam = response["query-continue"].values()[0]
            nextResponse = self.makeRequest(extraParams={
                continueParam.keys()[0]: continueParam.values()[0]
            }, saveUrl=True)
            del response["query-continue"]
            response["metadata"]["next"] = nextResponse["metadata"]["source"]
        outputFilename = self.getResponseFileName(responseIndex)
        json.dump(response, file(outputFilename, "w"))
        if nextResponse:
            self.saveResponses(nextResponse, responseIndex+1)

    def processResults(self, response=None, extracted=[], responseIndex=0):
        if not response:
            if self.fromFiles:
                response = self.loadResponseFile(0)
            else:
                response = self.makeRequest()

        for pageId, pageData in rget(response, ["query", "pages"]).items():
            extracted.append(self.performExtractions(pageData))

        if self.fromFiles:
            if "next" in response["metadata"]:
                nextResponse = self.loadResponseFile(responseIndex+1)
                extracted = self.processResults(nextResponse, extracted, responseIndex+1)
        else:
            if "query-continue" in response:
                continueParam = response["query-continue"].values()[0]
                nextResponse = self.makeRequest(extraParams={
                    continueParam.keys()[0]: continueParam.values()[0]
                })
                extracted = self.processResults(nextResponse, extracted)

        return extracted

def rget(dataDict, mapList):
    """Recursively retrieves a nested entity from a dictionary.
       See: http://stackoverflow.com/a/14692747"""
    return reduce(lambda d, k: d[k], mapList, dataDict)

parser = argparse.ArgumentParser()
parser.add_argument("config_file",
                    help="path to the config file that defines the scraping operations")
group = parser.add_mutually_exclusive_group()
group.add_argument("--save-only", action="store_true",
                   help="if this is specified, the raw JSON will only be saved to files, not processed")
group.add_argument("--from-files", action="store_true",
                   help="if this is specified, response data will be loaded from files previously saved using the --save-only flag")

args = parser.parse_args()

scraper = WikiScraper(args.config_file, args.from_files)

if args.save_only:
    # Just save the raw data for future processing
    scraper.saveResponses()
else:
    # Extract data
    extractedData = scraper.processResults()

    # TODO: This is also terrible
    yaml.safe_dump(extractedData, file(scraper.conf["outputFilename"], "w"))
    yaml.dump(extractedData, file(scraper.conf["outputFilename"].replace(".yml", "-loadable.yml"), "w"))
