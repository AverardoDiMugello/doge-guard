import argparse
import http.server
import json
import pandas as pd
import signal
import socketserver
import sys

parser = argparse.ArgumentParser()
parser.add_argument("csv_file", help="CSV file to serve")
args = parser.parse_args()

eval_lists = lambda x: x.strip("{}").replace("'","").split(", ")
fr_doc_analysis = pd.read_csv(args.csv_file, converters={"agencies": eval_lists, "agency_shorthand": eval_lists,})

class DogeGuardServer(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/results':
            filtered_data = fr_doc_analysis[fr_doc_analysis["llm_answer"].str.lower().str.startswith("yes")]
            def sum_cfr_div_info(entry):
                # TODO: 🤮
                entry = entry.strip("{}").split("), ")
                s = 0
                for e in entry:
                    print(e)
                    s += int(e.split(", ")[2].strip("()"))
                return s
            
            ordered_data = filtered_data.sort_values(by="cfr_divs_referenced_in", key=lambda col: col.apply(sum_cfr_div_info))
            to_serve = ordered_data.to_json()
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(to_serve).encode())
        else:
            self.send_error(404, "Not Found :(")

PORT = 3000
with socketserver.TCPServer(("", PORT), DogeGuardServer) as httpd:
    print(f"Serving at port {PORT}")
    httpd.serve_forever()

