import pandas as pd
from datetime import datetime
import os

today = datetime.now().strftime('%Y-%m-%d')
output_dir = os.path.join("output", today)
input_file = os.path.join(output_dir, "geopol_articles_raw.csv")
output_file = os.path.join(output_dir, "geopol_articles_clean.csv")

df = pd.read_csv(input_file)
df_sorted = df.sort_values(by="uri")
df_deduped = df_sorted.drop_duplicates(subset="uri")
df_deduped.to_csv(output_file, index=False)
print(f"Saved {len(df_deduped)} unique articles to {output_file}")
