import string
import sys
import hashlib
from math import sqrt

import util

weight = 0
ACCURACY_THRESHOLD = 0.03

conf = util.getConfig();

toBool = lambda str: True if str == "True" else False
DEBUG_ASSOC = toBool(conf["DEBUG"]["assoc"])
DEBUG_WEIGHT = toBool(conf["DEBUG"]["weight"])
DEBUG_ITEMID = toBool(conf["DEBUG"]["itemid"])
DEBUG_MATCH = toBool(conf["DEBUG"]["match"])

def hashtext(stringText):
    return hashlib.md5(str(stringText).encode('utf-8')).hexdigest()[:16]

def getItemId(entityName, text, cursor):

    tableName = entityName + 's'
    colName = entityName

    #check whether 16-char hash of this text exists already
    hashid = hashtext(text)

    SQL = 'SELECT hashid FROM ' + tableName + ' WHERE hashID = %s'
    if (DEBUG_ITEMID == True): print("DEBUG ITEMID: " + SQL)
    cursor.execute(SQL, (hashid))
    row = cursor.fetchone()

    if row:
        if (DEBUG_ITEMID == True): print("DEBUG ITEMID: item found, just return hashid:",row["hashid"], " for ", text )
        return row["hashid"]

    else:
        if (DEBUG_ITEMID == True): print("DEBUG ITEMID: no item found, insert new hashid into",tableName, " hashid:", hashid, " text:",text )
        SQL = 'INSERT INTO ' + tableName + ' (hashid, ' + colName + ') VALUES (%s, %s)'

        cursor.execute(SQL, (hashid, text))
        return hashid

def getAssociation(wordId, sentenceID, cursor):
    SQL = 'SELECT weight from associations WHERE word_id=%s AND sentence_id=%s'
    cursor.execute(SQL, (wordId, sentenceID))
    row = cursor.fetchone()

    if row:
        weight = row["weight"]
    else:
        weight = 0
    return weight

def setAssociation(words, sentenceID, cursor):
    totalChars = 0
    for word, n in words:
        totalChars += n * len(word)
    #print(totalChars)

    for word, n in words:
        wordId = getItemId('word', word, cursor)
        weight = sqrt(n / float(totalChars))

        association = getAssociation(wordId, sentenceID, cursor)

        if association > 0:
            SQL = 'UPDATE associations SET weight=%s where word_id=%s AND sentence_id=%s'
            cursor.execute(SQL, (association+weight, wordId, sentenceID))
        else:
            SQL = 'INSERT INTO associations (word_id, sentence_id, weight) VALUES (%s, %s, %s)'
            cursor.execute(SQL, (wordId, sentenceID, weight))

def getWords(inputSentence):
    wordsList = inputSentence.split()
    myDict = {}
    for words in wordsList:
        if words.lower() in myDict:
            val = myDict.get(words.lower())
            myDict[words.lower()] = val+1
        else:
            myDict[words.lower()] = 1
    myTuple = [(k, v) for k,v in myDict.iteritems()]
    return myTuple

def trainFunc(inputSentence, responseSentence, cursor):
    inputWords = getWords(inputSentence)
    responseSentenceID = getItemId('sentence', responseSentence, cursor)
    setAssociation(inputWords, responseSentenceID, cursor)

def getMatches(words, cursor):
    results = []
    listSize = 10

    totalChars = 0

    for word, n in words:
        totalChars += n*(len(word))

    for word, n in words:
        weight = (n / float(totalChars))
        SQL = 'INSERT INTO results \
                SELECT connection_id(), associations.sentence_id, sentences.sentence, %s * associations.weight/(1+sentences.used) \
                FROM words \
                INNER JOIN associations ON associations.word_id = words.hashid \
                INNER JOIN sentences ON sentences.hashid = associations.sentence_id \
                WHERE words.word = %s'
        cursor.execute(SQL, (weight, word))
    cursor.execute('SELECT sentence_id, sentence, SUM(weight) AS sum_weight \
                        FROM results \
                        WHERE connection_id = connection_id() \
                        GROUP BY sentence_id, sentence \
                        ORDER BY sum_weight DESC')

    for i in range(0, listSize):
        row = cursor.fetchone()
        if row:
            results.append([row["sentence_id"], row["sentence"], row["sum_weight"]])
        else:
            break
        cursor.execute('DELETE FROM results WHERE connection_id = connection_id()')
    return results

def feedback(sentenceID, cursor, previousSentenceID = None, sentiment = True):
    SQL = 'UPDATE sentences SET used = used+1 WHERE hashid = %s'
    cursor.execute(SQL, (sentenceID))

def chatStructure(cursor, humanSentence, weight):
    humanWords = getWords(humanSentence)
    matches = getMatches(humanWords, cursor)

    trainFlag = False

    if len(matches) == 0:
        botResponse = "Sorry! I don't know what to say.\n"
        trainFlag = True;
    else:
        sentenceID, botResponse, weight = matches[0]
        if weight > ACCURACY_THRESHOLD:
            feedback(sentenceID, cursor)
            trainFunc(botResponse, humanSentence, cursor)
        else:
            botResponse = "Sorry! I don't know what to say.\n"
            trainFlag = True
    return botResponse, weight, trainFlag

if __name__ == "__main__":

    conf = util.getConfig();

    DBHOST = conf["MySQL"]["server"]
    DBUSER = conf["MySQL"]["dbuser"]
    DBNAME = conf["MySQL"]["dbname"]
    PASSWORD = "rohil"

    print("Initializing the bot:")
    connection = util.dbConnection(DBHOST, DBUSER, PASSWORD, DBNAME)
    cursor = connection.cursor();
    print("Connected..")

    trainFlag = False
    botResponse = "Hello!"

    while True:
        print("Bot: " + botResponse)

        if trainFlag:
            print("Bot: Can you train me? Enter a response for me to learn. (Press enter to skip)\n")
            previousSentence = humanSentence
            humanSentence = raw_input(": ").strip()

            if len(humanSentence)>0:
                trainFunc(previousSentence, humanSentence, cursor)
            else:
                print("Bot: Ok moving on!\n")
                trainFlag = False
        humanSentence = raw_input("H: ").strip()
        
        if humanSentence == '' or humanSentence.lower() == 'exit' or humanSentence.lower() == 'quit':
            break
        botResponse, weight, trainFlag = chatStructure(cursor, humanSentence, weight)
        connection.commit()
