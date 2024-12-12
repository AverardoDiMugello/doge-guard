import argparse
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("input", help="Input .csv file of rag.py results")
parser.add_argument("--output", "-o", help="Output .csv file to save only the Yes entries of the input")

args = parser.parse_args()

results = pd.read_csv(args.input, dtype={"rule_length": int}, converters={"agencies": pd.eval, "agency-shorthand": pd.eval})
yes_results = results[results['answer'].str.lower().str.startswith("yes")]
yes_results.to_csv(args.output)
