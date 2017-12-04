import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import csv
import sys
import pickle

MODEL_NAME = './RandomForest.ml'

if len(sys.argv) > 1:
    FileName = sys.argv[1]
else:
    FileName = './DumpData/features.csv'
print("reading input from ",FileName)

df = pd.read_csv(filepath_or_buffer = FileName, )
print(str(len(df)), "rows loaded")

df.columns = df.columns[:].str.strip()
width = df.shape[1]

features = df.columns[1:width-1]
print("FEATURES = {}".format(features))

rf = RandomForestClassifier(n_jobs=2, n_estimators=100)
rf.fit(df[features], df['class'])

print("Saving model to " + MODEL_NAME +"\n")
with open(MODEL_NAME, 'wb') as f:
    pickle.dump(rf, f)
print("Complete")
