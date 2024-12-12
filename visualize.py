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
    plt.figure("Summary By Agency Part 1")
    rule_counts = results[["agency-shorthand"]].explode("agency-shorthand").value_counts()
    top_10 = rule_counts.nlargest(10)
    ax = top_10.plot.bar(x='agency-shorthand', y="count")
    
    ax.set_title("Top 10 Rule Issuers")
    ax.set_xlabel("Agencies")
    ax.set_ylabel("Number Of Rules Issued")  
    ax.tick_params(axis='x', labelrotation=-45)
    
    # Top 10 Unstatutory Issuers
    plt.figure("Summary By Agency Part 2")
    yes_results = results[results['answer'].str.lower().str.startswith("yes")]
    yes_counts = yes_results[["agency-shorthand"]].explode("agency-shorthand").value_counts()
    top_10 = yes_counts.nlargest(10)
    ax = top_10.plot.bar(x='agency-shorthand', y="count", width=0.4, position=1)
    
    ax.set_title("Top 10 Issuers Of Rules Labeled Unstatutory")
    ax.set_xlabel("Agencies")
    ax.set_ylabel("Number Of Rules Labeled Unstatutory")
    ax.tick_params(axis='x', labelrotation=-45)

    # rule_counts_of_top_10 = rule_counts[rule_counts.index.isin(top_10.index)]
    # pcnt_yes = top_10.div(rule_counts_of_top_10, fill_value=0)
    # pcnt_yes.plot.bar(ax=ax2_ov, x='agency-shorthand', y="count", width=0.4, position=0, color="orange")

    # Top 10 % Unstatutory
    plt.figure("Summary By Agency Part 3")
    yes_results = results[results['answer'].str.lower().str.startswith("yes")]
    yes_counts = yes_results[["agency-shorthand"]].explode("agency-shorthand").value_counts()
    yes_counts = yes_counts[yes_counts >= 3]
    pcnt_yes = yes_counts.div(rule_counts, fill_value=0)
    top_10 = pcnt_yes.nlargest(10)
    ax = top_10.plot.bar(y="count", rot=0)
    ax.set_title("Top 10 Most Frequent Issuers Of Rules Labeled Unstatutory")
    ax.set_xlabel("Agencies")
    ax.set_ylabel("Ratio Of Unstatutory Rules To Total Issued")
    ax.tick_params(axis='x', labelrotation=-45)

    # fig.tight_layout(pad=1.5)


def summary_by_rule(results, avoid_bug=True):
    plt.figure("Summary By Rule Part 1")
    answers = results['answer'].value_counts()
    answers.plot.pie(y='count', autopct='%1.1f%%')
    # TODO: annotation
    plt.title('Share of Rules Labeled Unstatutory')
    plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle

    # What percentage of tokens belong to unstatutory regulation?
    plt.figure("Summary By Rule Part 2")
    yes_results = results[results['answer'].str.lower().str.startswith("yes")]
    total_yes_tokens = yes_results["rule_length"].sum(skipna=True)

    no_results = results[results['answer'].str.lower().str.startswith("no")]
    total_no_tokens = no_results["rule_length"].sum(skipna=True)

    token_dist = pd.Series({"No": total_no_tokens, "Yes": total_yes_tokens})
    token_dist.plot.pie(autopct='%1.1f%%')
    
    plt.title('Share of Text Belonging to Regulation Labeled Unstatutory')
    plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle

    # For regulations in a given bucket of text length, how often were rules labeled unstatutory?
    if not avoid_bug:
        plt.figure("Summary By Rule Part 3")
        rule_lengths = results[["answer", "rule_length"]]
        bins = pd.cut(results['rule_length'], bins=[0, 1e4, 1e5, 1e6, float("inf")])  # Adjust the number of bins as needed
        num_per_bin = rule_lengths["answer"].groupby(bins).count()
        num_yes_per_bin = rule_lengths[rule_lengths['answer'].str.lower().str.startswith("yes")].groupby(bins)['answer'].count()
        pcnt_yes_per_bin = num_yes_per_bin.div(num_per_bin)
        pcnt_yes_per_bin.plot.bar(rot=0.45, width=0.6)

        plt.title('Percentage of Unstatutory Regulation Grouped by Regulation Size')
    

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="+", help="Input .csv file of rag.py results")
    args = parser.parse_args()
    
    results = [pd.read_csv(input, dtype={"rule_length": int}, converters={"agencies": pd.eval, "agency-shorthand": pd.eval}) for input in args.input]
    results = pd.concat(results)

    summary_by_rule(results)
    summary_by_agency(results)
    plt.show()

    