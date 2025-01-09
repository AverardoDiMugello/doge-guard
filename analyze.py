import math
import pandas as pd
import matplotlib.pyplot as plt

def make_autopct(values):
    def my_autopct(pct):
        total = sum(values)
        val = int(round(pct*total/100.0))
        return '{p:.2f}%  ({v:d})'.format(p=pct,v=val)
    return my_autopct


def summary_by_agency(results):
    # fig, (ax1, ax2, ax3) = plt.subplots(1, 3, num="Summary By Agency")
    # ax2_ov = ax2.twinx()

    # Top 10 Issuers
    fig, ax = plt.subplots(1, 1, num="Summary By Agency Part 1")
    rule_counts = results[["agency-shorthand"]].explode("agency-shorthand").value_counts().reset_index()
    top_10 = rule_counts.nlargest(10, columns="count")
    top_10.plot.bar(ax=ax, x='agency-shorthand', y="count")
    
    ax.set_title("Top 10 Rule Issuers")
    ax.set_xlabel("Agencies")
    ax.set_ylabel("Number Of Rules Issued")  
    ax.tick_params(axis='x', labelrotation=-45)
    ax.get_legend().remove()
    
    # Top 10 Unstatutory Issuers
    fig, ax = plt.subplots(1, 1, num="Summary By Agency Part 2")
    yes_results = results[results['answer'].str.lower().str.startswith("yes")]
    yes_counts = yes_results[["agency-shorthand"]].explode("agency-shorthand").value_counts().reset_index()
    top_10 = yes_counts.nlargest(10, columns="count")
    top_10.plot.bar(ax=ax, x='agency-shorthand', y="count", width=0.4, position=1)
    
    ax.set_title("Top 10 Issuers Of Rules Labeled Unstatutory")
    ax.set_xlabel("Agencies")
    ax.set_ylabel("Number Of Rules Labeled Unstatutory")
    ax.tick_params(axis='x', labelrotation=-45)
    ax.get_legend().remove()

    # rule_counts_of_top_10 = rule_counts[rule_counts.index.isin(top_10.index)]
    # pcnt_yes = top_10.div(rule_counts_of_top_10, fill_value=0)
    # pcnt_yes.plot.bar(ax=ax2_ov, x='agency-shorthand', y="count", width=0.4, position=0, color="orange")

    # Top 10 % Unstatutory (min 5)
    fig, ax = plt.subplots(1, 1, num="Summary By Agency Part 3")
    rule_counts_min_5 = rule_counts[rule_counts["count"] >= 5]
    yes_counts_min_5 = yes_counts[yes_counts["agency-shorthand"].isin(rule_counts_min_5["agency-shorthand"])]
    rule_counts_of_yes_counts_min_5 = rule_counts_min_5[rule_counts_min_5["agency-shorthand"].isin(yes_counts_min_5["agency-shorthand"])]
    rule_counts_of_yes_counts_min_5 = rule_counts_of_yes_counts_min_5.sort_values("agency-shorthand").reset_index(drop=True)
    yes_counts_min_5 = yes_counts_min_5.sort_values("agency-shorthand").reset_index(drop=True)
    pcnt_yes = yes_counts_min_5.copy()
    pcnt_yes["count"] = yes_counts_min_5["count"].div(rule_counts_of_yes_counts_min_5["count"])
    top_10 = pcnt_yes.nlargest(10, columns="count")
    top_10.plot.bar(ax=ax, x="agency-shorthand", y="count", rot=0)

    ax.set_title("Top 10 Most Frequent Issuers Of Rules Labeled Unstatutory (Min. 5 Rules)", wrap=True)
    ax.set_xlabel("Agencies")
    ax.set_ylabel("Ratio Of Unstatutory Rules To Total Issued")
    ax.tick_params(axis='x', labelrotation=-45)
    ax.get_legend().remove()

    # Top 10 % Unstatutory (min 100)
    fig, ax = plt.subplots(1, 1, num="Summary By Agency Part 4")
    rule_counts_min_5 = rule_counts[rule_counts["count"] >= 100]
    yes_counts_min_5 = yes_counts[yes_counts["agency-shorthand"].isin(rule_counts_min_5["agency-shorthand"])]
    rule_counts_of_yes_counts_min_5 = rule_counts_min_5[rule_counts_min_5["agency-shorthand"].isin(yes_counts_min_5["agency-shorthand"])]
    rule_counts_of_yes_counts_min_5 = rule_counts_of_yes_counts_min_5.sort_values("agency-shorthand").reset_index(drop=True)
    yes_counts_min_5 = yes_counts_min_5.sort_values("agency-shorthand").reset_index(drop=True)
    pcnt_yes = yes_counts_min_5.copy()
    pcnt_yes["count"] = yes_counts_min_5["count"].div(rule_counts_of_yes_counts_min_5["count"])
    top_10 = pcnt_yes.nlargest(10, columns="count")
    top_10.plot.bar(ax=ax, x="agency-shorthand", y="count", rot=0)
    
    ax.set_title("Top 10 Most Frequent Issuers Of Rules Labeled Unstatutory (Min. 100 Rules)", wrap=True)
    ax.set_xlabel("Agencies")
    ax.set_ylabel("Ratio Of Unstatutory Rules To Total Issued")
    ax.tick_params(axis='x', labelrotation=-45)
    ax.get_legend().remove()


def summary_by_rule(results):
    # What percentage of rules had contested legality?
    plt.figure("Summary By Rule Part 1")
    answers = results['answer'].value_counts()
    answers.plot.pie(autopct='%1.1f%%', labels=["Statutory", "Unstatutory"])
    plt.title('Share of Rules Labeled Unstatutory')
    plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle
    plt.ylabel('')

    # What percentage of tokens belong to unstatutory regulation?
    plt.figure("Summary By Rule Part 2")
    yes_results = results[results['answer'].str.lower().str.startswith("yes")]
    total_yes_tokens = yes_results["rule_length"].sum(skipna=True)
    no_results = results[results['answer'].str.lower().str.startswith("no")]
    total_no_tokens = no_results["rule_length"].sum(skipna=True)
    token_dist = pd.Series({"No": total_no_tokens, "Yes": total_yes_tokens})
    token_dist.plot.pie(autopct='%1.1f%%', labels=["Statutory", "Unstatutory"])
    plt.title('Share of Text Belonging to Rules Labeled Unstatutory')
    plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle

    # For regulations in a given bucket of text length, how often were rules labeled unstatutory?
    plt.figure("Summary By Rule Part 3")
    rule_lengths = results[["answer", "rule_length"]]
    bins = pd.cut(rule_lengths['rule_length'], bins=[0, 1e4, 1e5, 1e6, float("inf")])  # Adjust the number of bins as needed
    num_per_bin = rule_lengths["answer"].groupby(bins).count()
    num_yes_per_bin = rule_lengths[rule_lengths['answer'].str.lower().str.startswith("yes")].groupby(bins)['answer'].count()
    pcnt_yes_per_bin = num_yes_per_bin.div(num_per_bin)
    ax = pcnt_yes_per_bin.plot.bar(rot=0.45, width=0.6)
    ax.set_ylabel("Ratio of Unstatutory Rules to Total Issued")
    ax.set_xlabel("Rule Length (characters)")
    ax.set_xticklabels(["<10k", "10k - 100k", "100k - 1M", ">1M"])
    plt.title('Percentage of Unstatutory Rules Grouped by Rule Size')
    

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="+", help="Input .csv file of rag.py results")
    args = parser.parse_args()
    
    # converters={"agencies": pd.eval, "agency-shorthand": pd.eval}
    eval_lists = lambda x: x.strip("[]").replace("'","").split(", ")
    results = [pd.read_csv(input, dtype={"rule_length": int}, converters={"agencies": eval_lists, "agency-shorthand": eval_lists}) for input in args.input]
    results = pd.concat(results, ignore_index=True)
    summary_by_rule(results)
    summary_by_agency(results)
    plt.show()

    