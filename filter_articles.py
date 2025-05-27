import pandas as pd
from datetime import datetime
import os

def filter_articles(input_file, output_file):
    df = pd.read_csv(input_file)

    # Sample filtering rules
    if 'socialScore' in df.columns:
        df = df[df['socialScore'] > 50]
    else:
        print("Warning: 'socialScore' column missing, skipping that filter.")

    df = df[df['sentiment'] > -0.5]
    df = df[df['body'].str.len() > 500]  # Adjust as needed

    df.to_csv(output_file, index=False)
    print(f"Saved {len(df)} filtered articles to {output_file}")

if __name__ == "__main__":
    today = datetime.now().strftime('%Y-%m-%d')
    output_dir = os.path.join("output", today)
    input_csv = os.path.join(output_dir, "geopol_articles_clean.csv")
    output_csv = os.path.join(output_dir, "geopol_articles_final.csv")

    filter_articles(input_csv, output_csv)
