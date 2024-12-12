import math
import pandas as pd
import matplotlib.pyplot as plt

def make_autopct(values):
    def my_autopct(pct):
        total = sum(values)
        val = int(round(pct*total/100.0))
        return '{p:.2f}%  ({v:d})'.format(p=pct,v=val)
    return my_autopct


def summary_by_rule_size(results):
    # What percentage of tokens belong to unstatutory regulation?
    plt.figure()
    yes_results = results[results['answer'].str.lower().str.startswith("yes")]
    total_yes_tokens = yes_results["rule_length"].sum(skipna=True)

    no_results = results[results['answer'].str.lower().str.startswith("no")]
    total_no_tokens = no_results["rule_length"].sum(skipna=True)

    token_dist = pd.Series({"Yes": total_yes_tokens, "No": total_no_tokens})
    print(token_dist)
    token_dist.plot.pie(autopct='%1.1f%%')

    plt.title('Share of Tokens Belonging to Unstatutory Regulation')
    plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle

    # Percenta
    plt.figure()
    rule_lengths = results[["answer", "rule_length"]]
    bins = pd.cut(results['rule_length'], bins=[0, 1e4, 1e5, 1e6, float("inf")])  # Adjust the number of bins as needed
    num_per_bin = rule_lengths["answer"].groupby(bins).count()
    print(num_per_bin.head())
    num_yes_per_bin = rule_lengths[rule_lengths['answer'].str.lower().str.startswith("yes")].groupby(bins)['answer'].count()
    print(num_yes_per_bin.head())
    pcnt_yes_per_bin = num_yes_per_bin.div(num_per_bin)
    pcnt_yes_per_bin.plot.bar(rot=0.45)

    plt.title('Percentage of Unstatutory Regulation Grouped by Regulation Size')
    # plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle


def summary_by_agency(results):
    fig, (ax1, ax2) = plt.subplots(1, 2, num="Summary By Agency", figsize=(8, 6))
    ax2_ov = ax2.twinx()

    # Top 10 Issuers
    rule_counts = results[["agency-shorthand"]].explode("agency-shorthand").value_counts()
    top_10 = rule_counts.nlargest(10)
    top_10.plot.bar(ax=ax1, x='agency-shorthand', y="count")
    
    ax1.set_title("Top 10 Rule Issuers")
    ax1.set_xlabel("Agencies")
    ax1.set_ylabel("Number Of Final Rules Issued")  
    ax1.tick_params(axis='x', labelrotation=-45)
    
    # Top 10 Unstatutory Issuers
    yes_results = results[results['answer'].str.lower().str.startswith("yes")]
    yes_counts = yes_results[["agency-shorthand"]].explode("agency-shorthand").value_counts()
    top_10 = yes_counts.nlargest(10)
    top_10.plot.bar(ax=ax2, x='agency-shorthand', y="count", width=0.4, position=1)
    
    rule_counts_of_top_10 = rule_counts[rule_counts.index.isin(top_10.index)]
    pcnt_yes = top_10.div(rule_counts_of_top_10, fill_value=0)
    pcnt_yes.plot.bar(ax=ax2_ov, x='agency-shorthand', y="count", width=0.4, position=0, color="orange")
    
    ax2.set_title("Top 10 Issuers Of Unstatutory Rules")
    ax2.set_xlabel("Agencies")
    ax2.set_ylabel("Number Of Final Rules Labeled Unstatutory")
    ax2_ov.set_ylabel("Ratio Of Unstatutory To Issued")
    ax2.tick_params(axis='x', labelrotation=-45)
    lines, labels = ax2.get_legend_handles_labels()
    lines_ov, labels_ov = ax2_ov.get_legend_handles_labels()
    ax2.legend(lines + lines_ov, labels + labels_ov, loc=0)

    fig.tight_layout(pad=1.5)


def summary_by_rule(results):
    plt.figure("Summary By Rule")
    answers = results['answer'].value_counts()
    answers.plot.pie(y='count', autopct='%1.1f%%')
    # TODO: annotation
    plt.title('Distribution of Values in answer')
    plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="+", help="Input .csv file of rag.py results")
    parser.add_argument("--output", "-o", help="Output .csv file to save only the Yes entries of the input")
    parser.add_argument("--no-graphs", help="Set flag to suppress the summary graphs")

    args = parser.parse_args()
    
    results = [pd.read_csv(input, dtype={"rule_length": int}, converters={"agencies": pd.eval, "agency-shorthand": pd.eval}) for input in args.input]
    results = pd.concat(results)    

    # # Top 10 % Unstatutory
    # plt.figure()
    # # Get the top 10 rows
    # rule_counts = results[["agency-shorthand"]].explode("agency-shorthand").value_counts()

    # yes_results = results[results['answer'].str.lower().str.startswith("yes")]
    # yes_counts = yes_results[["agency-shorthand"]].explode("agency-shorthand").value_counts()
    # yes_counts = yes_counts[yes_counts >= 5]
    # print(yes_counts.head())
    # pcnt_yes = yes_counts.div(rule_counts, fill_value=0)
    # print(pcnt_yes.head())
    # top_10 = pcnt_yes.nlargest(10)
    # print(top_10.head())
    # ax = top_10.plot.bar(y="count", rot=0)
    # ax.set_title("Most Frequent Issuers Of Unstatutory Rules (min 5, 2023-2024)")
    # ax.set_xlabel("Agencies")
    # ax.set_ylabel("Ratio Of Unstatutory Rules To Total Issued")

    if args.output:
        print("Ignoring for now")
    
    if not args.no_graphs:
        summary_by_rule(results)
        summary_by_agency(results)
        # summary_by_rule_size(results)
        plt.show()

    