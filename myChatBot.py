import re
import string
import sys
import hashlib
from math import sqrt
import features
import os
import util
import pickle
import random
from sklearn.ensemble import RandomForestClassifier
from nltk.parse.stanford import StanfordDependencyParser

weight = 0
ACCURACY_THRESHOLD = 0.03

conf = util.getConfig();

toBool = lambda str: True if str == "True" else False
DEBUG_ASSOC = toBool(conf["DEBUG"]["assoc"])
DEBUG_WEIGHT = toBool(conf["DEBUG"]["weight"])
DEBUG_ITEMID = toBool(conf["DEBUG"]["itemid"])
DEBUG_MATCH = toBool(conf["DEBUG"]["match"])

STATEMENTS = ["Thanks, I've made a note of that.",
                    "Thanks for telling me that.",
                    "OK, I've stored that information.",
                    "OK, I've made a note of that."]

JAVA_HOME = conf["Java"]["bin"]
STANFORD_NLP = conf["StanfordNLP"]["corejar"]
STANFORD_MODEL = conf["StanfordNLP"]["modelsjar"]

MODEL_LOC = "./RandomForest.ml"
os.environ['JAVAHOME'] = JAVA_HOME

# Stackover flow code snippet
def hashtext(stringText):
    return hashlib.md5(str(stringText).encode('utf-8')).hexdigest()[:16]

def getItemId(entityName, text, cursor):

    tableName = entityName + 's'
    colName = entityName

    alreadyExists = False

    #check whether 16-char hash of this text exists already
    hashid = hashtext(text)

    SQL = 'SELECT hashid FROM ' + tableName + ' WHERE hashID = %s'
    if (DEBUG_ITEMID == True): print("DEBUG ITEMID: " + SQL)
    cursor.execute(SQL, (hashid))
    row = cursor.fetchone()

    if row:
        if (DEBUG_ITEMID == True): print("DEBUG ITEMID: item found, just return hashid:",row["hashid"], " for ", text )
        alreadyExists = True
        return row["hashid"], alreadyExists

    else:
        if (DEBUG_ITEMID == True): print("DEBUG ITEMID: no item found, insert new hashid into",tableName, " hashid:", hashid, " text:",text )
        SQL = 'INSERT INTO ' + tableName + ' (hashid, ' + colName + ') VALUES (%s, %s)'
        alreadyExists = False
        cursor.execute(SQL, (hashid, text))
        return hashid, alreadyExists

def getAssociation(wordId, sentenceId, cursor):
    SQL = 'SELECT weight from associations WHERE word_id = %s AND sentence_id = %s'
    if (DEBUG_ASSOC == True): print("DEBUG_ASSOC:", SQL,word_id, sentence_id)
    cursor.execute(SQL, (wordId, sentenceId))
    row = cursor.fetchone()

    if row:
        weight = row["weight"]
    else:
        weight = 0
    return weight

def setAssociation(words, sentenceId, cursor):
    totalChars = 0
    for word, n in words:
        totalChars += n * len(word)
    #print(totalChars)

    for word, n in words:
        wordId, exists = getItemId('word', word, cursor)
        weight = sqrt(n / float(totalChars))

        association = getAssociation(wordId, sentenceId, cursor)

        if association > 0:
            SQL = 'UPDATE associations SET weight=%s where word_id=%s AND sentence_id=%s'
            cursor.execute(SQL, (association+weight, wordId, sentenceId))
        else:
            SQL = 'INSERT INTO associations (word_id, sentence_id, weight) VALUES (%s, %s, %s)'
            cursor.execute(SQL, (wordId, sentenceId, weight))

def getWords(inputSentence):
    wordsList = inputSentence.split()
    myDict = {}
    for words in wordsList:
        if words.lower() in myDict:
            val = myDict.get(words.lower())
            myDict[words.lower()] = val+1
        else:
            myDict[words.lower()] = 1
    myTuple = [(k, v) for k,v in myDict.items()]
    return myTuple

def trainFunc(inputSentence, responseSentence, cursor):
    inputWords = getWords(inputSentence)
    responseSentenceID, exists = getItemId('sentence', responseSentence, cursor)
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

def sentenceForestClass(sentence):
    with open(MODEL_LOC, 'rb') as f:
        rf = pickle.load(f, encoding='latin1')

    id = hashtext(sentence)  #features needs an ID passing in at moment - maybe redundant?
    fseries = features.features_series(features.features_dict(id,sentence))
    width = len(fseries)
    fseries = fseries[1:width-1]  #All but the first and last item (strip ID and null class off)

    #Get a classification prediction from the Model, based on supplied features
    sentenceClass = rf.predict([fseries])[0].strip()

    return sentenceClass

def getAnswer(sentence, cursor):
    results = []
    listSize = 10

    topic,subj,obj,lastNounA,lastNounB = getGrammar(sentence)
    subj_topic = subj + topic
    subj_obj = subj + obj

    full_grammar = topic + subj + obj + lastNounA + lastNounB
    full_grammar_in = ' ,'.join(list(map(lambda x: '%s', full_grammar))) # SQL in-list fmt
    subj_in = ' ,'.join(list(map(lambda x: '%s', subj_topic))) # SQL in-list fmt
    SQL1 = """SELECT count(*) score, statements.sentence_id sentence_id, sentences.sentence
    FROM statements
    INNER JOIN words ON statements.word_id = words.hashid
    INNER JOIN sentences ON sentences.hashid = statements.sentence_id
    WHERE words.word IN (%s) """
    SQL2 = """
    AND statements.sentence_id in (
        SELECT sentence_id
        FROM statements
        INNER JOIN words ON statements.word_id = words.hashid
        WHERE statements.class in ('subj','topic')  -- start with subset of statements covering question subj/topic
        AND words.word IN (%s)
    )
    GROUP BY statements.sentence_id, sentences.sentence
    ORDER BY score desc
    """

    SQL1 = SQL1 % full_grammar_in
    SQL2 = SQL2 % subj_in
    SQL = SQL1 + SQL2

    cursor.execute(SQL, full_grammar + subj_topic)
    for i in range(0,listSize):
        row = cursor.fetchone()
        if row:
            results.append([row["sentence_id"], row["score"], row["sentence"]])
            #if (DEBUG_ANSWER == True): print("DEBUG_ANSWER: ", row["sentence_id"], row["score"], row["sentence"])
        else:
            break

    # increment score for each subject / object match - sentence words are in row[2] col
    i = 0
    top_score = 0 # top score
    for row in results:
        word_count_dict = getWords(row[2])
        subj_obj_score = sum( [value for key, value in word_count_dict if key in subj_obj] )
        results[i][1] = results[i][1] + subj_obj_score
        if results[i][1] > top_score: top_score = results[i][1]
        i = i + 1

    #filter out the top-score results
    results = [l for l in results if l[1] == top_score]

    return results

def chatStructure(cursor, humanSentence, weight):
    humanWords = getWords(humanSentence)
    #matches = getMatches(humanWords, cursor)
    weight  = 0

    trainFlag = False
    checkStore = False

    classification = sentenceForestClass(humanSentence)

    if classification == 'S':
        checkStore = True
        botResponse = "Ok!, I think that is a statement\n"
    elif classification == 'Q':
        answers = getAnswer(humanSentence, cursor)
        if len(answers) > 0:
            answer = ""
            for a in answers:
                answer = answer+"\n"+a[2]
            botResponse = answer
            weight = answers[0:1]
        else:
            botResponse = "I don't have an answer for that.\n"
    elif classification == 'C':
        matches = getMatches(humanWords, cursor)
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
    return botResponse, weight, trainFlag, checkStore

def getGrammar(sentence):
    os.environ['JAVAHOME'] = JAVA_HOME  # Set this to where the JDK is
    dependency_parser = StanfordDependencyParser(path_to_jar=STANFORD_NLP, path_to_models_jar=STANFORD_MODEL)

    regexpSubj = re.compile(r'subj')
    regexpObj = re.compile(r'obj')
    regexpMod = re.compile(r'mod')
    regexpNouns = re.compile("^N.*|^PR.*")

    sentence = sentence.lower()

    #return grammar Compound Modifiers for given word
    def get_compounds(triples, word):
        compounds = []
        for t in triples:
            if t[0][0] == word:
                if t[2][1] not in ["CC", "DT", "EX", "LS", "RP", "SYM", "TO", "UH", "PRP"]:
                    compounds.append(t[2][0])

        mods = []
        for c in compounds:
            mods.append(get_modifier(triples, c))

        compounds.append(mods)
        return compounds

    def get_modifier(triples, word):
        modifier = []
        for t in triples:
            if t[0][0] == word:
                 if regexpMod.search(t[1]):
                     modifier.append(t[2][0])

        return modifier

    #Get grammar Triples from Stanford Parser
    result = dependency_parser.raw_parse(sentence)
    dep = next(result)  # get next item from the iterator result

    #Get word-root or "topic"
    root = [dep.root["word"]]
    root.append(get_compounds(dep.triples(), root[0]))
    root.append(get_modifier(dep.triples(), root[0]))

    subj = []
    obj = []
    lastNounA = ""
    lastNounB = ""

    for t in dep.triples():
        if regexpSubj.search(t[1]):
            subj.append(t[2][0] )
            subj.append(get_compounds(dep.triples(),t[2][0]))
        if regexpObj.search(t[1]):
            obj.append(t[2][0])
            obj.append(get_compounds(dep.triples(),t[2][0]))
        if regexpNouns.search(t[0][1]):
            lastNounA = t[0][0]
        if regexpNouns.search(t[2][1]):
            lastNounB = t[2][0]

    return list(util.flatten([root])), list(util.flatten([subj])), list(util.flatten([obj])), list(util.flatten([lastNounA])), list(util.flatten([lastNounB]))

def storeResponse(sentence, store):
    sentenceID, exists = getItemId('sentence', sentence, cursor)
    SQL = 'UPDATE sentences SET used=used+1 WHERE hashid=%s'
    cursor.execute(SQL, (sentenceID))

    if not exists:
        topic, subj, obj, lastNounA, lastNounB = getGrammar(sentence)
        lastNouns = lastNounA + lastNounB

                #topic
        for word in topic:
            wordId, exists = getItemId('word', word, cursor)
            SQL = "INSERT INTO statements (sentence_id, word_id, class) VALUES (%s, %s, %s) "
            cursor.execute(SQL, (sentenceID, wordId, 'topic'))
        #subj
        for word in subj:
            word_id, exists = getItemId('word', word, cursor)
            SQL = "INSERT INTO statements (sentence_id, word_id, class) VALUES (%s, %s, %s) "
            cursor.execute(SQL, (sentenceID, wordId, 'subj'))

        #obj
        for word in obj:
            word_id, exists = getItemId('word', word, cursor)
            SQL = "INSERT INTO statements (sentence_id, word_id, class) VALUES (%s, %s, %s) "
            cursor.execute(SQL, (sentenceID, wordId, 'obj'))

        #lastNouns
        for word in lastNouns:
            word_id, exists = getItemId('word', word, cursor)
            SQL = "INSERT INTO statements (sentence_id, word_id, class) VALUES (%s, %s, %s) "
            cursor.execute(SQL, (sentenceID, wordId, 'nouns'))

if __name__ == "__main__":

    conf = util.getConfig();

    DBHOST = conf["MySQL"]["server"]
    DBUSER = conf["MySQL"]["dbuser"]
    DBNAME = conf["MySQL"]["dbname"]
    PASSWORD = "rohil"

    print("Initializing Pikachu:")
    connection = util.dbConnection(DBHOST, DBUSER, PASSWORD, DBNAME)
    cursor = connection.cursor();
    print("Connected..")

    trainFlag = False
    checkStore = False
    botResponse = "Hello!"

    while True:
        print("Pikaa: " + botResponse)

        if trainFlag:
            print("Pikaa: Can you train me? Enter a response for me to learn. (Press enter to skip)\n")
            previousSentence = humanSentence
            humanSentence = input(": ").strip()

            if len(humanSentence)>0:
                trainFunc(previousSentence, humanSentence, cursor)
                print("Pikaa: Thanks, I've noted that.\n")
            else:
                print("Pikaa: Ok moving on!\n")
                trainFlag = False

        if checkStore:
            print("Pikaa: Shall I store that as a future reference? ('yes' to store)")
            previousSentence = humanSentence
            humanSentence = input("H: ").strip()
            if humanSentence.lower() == 'yes':
                storeResponse(previousSentence, cursor)
                print(random.choice(STATEMENTS))
            else:
                print("Pikaa: Ok, moving on!")
                checkStore = False

        humanSentence = input("H: ").strip()

        if humanSentence == '' or humanSentence.lower() == 'exit' or humanSentence.lower() == 'quit':
            break
        botResponse, weight, trainFlag, checkStore = chatStructure(cursor, humanSentence, weight)
        connection.commit()
