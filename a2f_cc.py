import os
import pandas as pd

my_results = pd.read_csv(os.path.join("documents", "results", "rules_2024_all_results.csv"))
my_results["lower_title"] = my_results["title"].str.lower()
print("My Results:", len(my_results.index))
print(my_results.columns)
print()

a2f_results = pd.read_csv(os.path.join("documents", "regulation_list.csv"))
a2f_results["lower_title"] = a2f_results["Regulation"].str.lower()
print("A2F Results:", len(a2f_results.index))
print(a2f_results.columns)
print()

a2f_2024 = a2f_results[a2f_results["Year"] == 2024]
print("A2F 2024:", len(a2f_2024.index))
print(a2f_2024.columns)
print(a2f_2024.head())
print()

merged = pd.merge(my_results, a2f_2024, on="lower_title").dropna()
merged["cost_float"] = merged["Cost"].str.replace('b', 'E+09').str.replace('m', 'E+06').str.replace('k', 'E+03').astype(float)
print("Merged:", len(merged.index))
print(merged.head())
print()

yes = merged[merged["answer"].str.lower().str.startswith("yes")]
print("Yes Matches:", len(yes.index))
print(yes.head())
print()

sorted = yes.sort_values(by="cost_float", ascending=False)
print("Sorted:", len(sorted.index))
print(sorted.head())
print()

sorted.to_csv(os.path.join("documents", "2024_rules_with_estimates.csv"))
print("Saved!")
# print("Not saved.")
