#!/usr/bin/env python

import argparse
import copy
import hashlib
import json
import mwparserfromhell
import os.path
import pprint
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

    def executeFunction(self, fnName, var, addtlArgs=None):
        parts = fnName.split(".")
        fn = None
        if len(parts) == 2:
            mod = __import__(parts[0])
            fn = getattr(mod, parts[1])
        elif len(parts) == 1:
            fn = getattr(self, fnName)
        else:
            raise Exception("Invalid custom processor '%s'" % fnName)

        if addtlArgs:
            return fn(var, *addtlArgs)
        else:
            return fn(var)

    def hashPageText(self, data):
        data["textHash"] = hashlib.sha256(data["text"].encode("utf-8")).hexdigest()
        del data["text"]

        return data

    # TODO: Clean this mess up a bit...
    def performExtractions(self, pageData):
        text = rget(pageData, ["revisions", 0, "*"])
        textPreExtractionOps = rget(self.conf, ["preExtraction", "text"])
        if textPreExtractionOps:
            for op in textPreExtractionOps:
                args = op["args"] if "args" in op else None
                text = self.executeFunction(op["function"], text, args)
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

        # Handle any post-extraction operations defined in the configuration
        if "postExtraction" in self.conf:
            postExtractionOps = self.conf["postExtraction"]
            for op in postExtractionOps:
                args = op["args"] if "args" in op else None
                data = self.executeFunction(op["function"], data, args)

        return data

    def generateContinueParam(self, response):
        continueParam = response["query-continue"].values()[0]
        continueDict = {
            continueParam.keys()[0]: continueParam.values()[0]
        }

        return continueDict

    def saveResponses(self, response, responseIndex=0):
        # If there's a continuation, grab it so we can save the "next" url
        # with the current response
        nextResponse = None
        if "query-continue" in response:
            continueParam = self.generateContinueParam(response)
            nextResponse = self.makeRequest(extraParams=continueParam, saveUrl=True)
            del response["query-continue"]
            response["metadata"]["next"] = nextResponse["metadata"]["source"]

        # Save the response
        outputFilename = self.getResponseFileName(responseIndex)
        with open(outputFilename, "w") as responseFile:
            json.dump(response, responseFile)

        # Recurse while we have additional responses to save
        if nextResponse:
            self.saveResponses(nextResponse, responseIndex+1)

    def processResults(self, response, extracted=[], responseIndex=0):
        for pageId, pageData in rget(response, ["query", "pages"]).items():
            extracted.append(self.performExtractions(pageData))

        # Continue processing "next" responses while we have them
        if self.fromFiles:
            if "next" in response["metadata"]:
                nextResponse = self.loadResponseFile(responseIndex+1)
                extracted = self.processResults(nextResponse, extracted, responseIndex+1)
        else:
            if "query-continue" in response:
                continueParam = self.generateContinueParam(response)
                nextResponse = self.makeRequest(extraParams=continueParam)
                extracted = self.processResults(nextResponse, extracted)

        return extracted

def rget(dataDict, mapList):
    """Recursively retrieves a nested entity from a dictionary.
       See: http://stackoverflow.com/a/14692747"""
    try:
        return reduce(lambda d, k: d[k], mapList, dataDict)
    except KeyError as ke:
        return None

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
    response = scraper.makeRequest(saveUrl=True)
    scraper.saveResponses(response)
else:
    # Extract data
    if scraper.fromFiles:
        response = scraper.loadResponseFile(0)
    else:
        response = scraper.makeRequest()
    extractedData = scraper.processResults(response)

    # TODO: This is also terrible
    yaml.safe_dump(extractedData, file(scraper.conf["outputFilename"], "w"))
    yaml.dump(extractedData, file(scraper.conf["outputFilename"].replace(".yml", "-loadable.yml"), "w"))
