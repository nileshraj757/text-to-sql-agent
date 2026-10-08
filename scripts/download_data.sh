#!/usr/bin/env bash
# Downloads the 9 Olist CSVs from a public Hugging Face mirror (Apache-2.0 tagged).
# The original lives on Kaggle (CC BY-NC-SA 4.0): check the license before publishing derived data.
set -euo pipefail
mkdir -p data/raw && cd data/raw
for f in olist_customers_dataset olist_geolocation_dataset olist_order_items_dataset \
         olist_order_payments_dataset olist_order_reviews_dataset olist_orders_dataset \
         olist_products_dataset olist_sellers_dataset product_category_name_translation; do
  curl -sfL -o "$f.csv" "https://huggingface.co/datasets/MafiaAzulBr/olistcsv/resolve/main/archive/$f.csv"
done
ls -la
