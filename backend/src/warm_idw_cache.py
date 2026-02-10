# warm_idw_cache.py
from pipeline import ensure_idw_outputs

CELL = 500
KNN = 32
MAX_DIM = 1400

# choose step size here
K_VALUES = [round(k, 1) for k in [x / 10 for x in range(11, 61)]]
# -> 1.1, 1.2, ..., 6.0

def main():
    print(f"Warming cache for {len(K_VALUES)} k values…")

    for k in K_VALUES:
        print(f"  k={k}")
        ensure_idw_outputs(
            k=k,
            cell=CELL,
            knn=KNN,
            want_png=True,
            want_table=True,
            want_reg=True,
            max_dim=MAX_DIM,
        )

    print("Cache warm complete.")

if __name__ == "__main__":
    main()
