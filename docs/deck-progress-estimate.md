# Deck Progress – how the estimate is calculated

## Symbols

| Symbol | Meaning |
|---|---|
| $t$ | today; days are Anki days (they start at your *Next day starts at* hour) |
| $n_d$ | notes (or cards) answered for the first time on day $d$, in the counter and goal decks |
| $A$ | study days: $\{\,d \le t : n_d > 0\,\}$, newest first: $a_1 > a_2 > \dots$ |
| $R$ | study days in the last 4 weeks: $\{\,d \in A : d > t - 28\,\}$ |
| $G$ | goal total: notes (or cards) in the counter decks and goal decks |
| $C$ | what the counter counts (its card states, e.g. answered or mature only) |

## Days used for the pace

$$
S =
\begin{cases}
R & \text{if } |R| \ge 5 \\
\{a_1, \dots, a_{\min(10,\,|A|)}\} & \text{otherwise}
\end{cases}
\qquad
s =
\begin{cases}
\dfrac{|R|}{28} & \text{if } |R| \ge 5 \\
1 & \text{otherwise}
\end{cases}
$$

No estimate is shown while $|S| < 3$.

## Pace

$S$ sorted newest first as $s_1, s_2, \dots, s_k$:

$$
p = \frac{\sum_{i=1}^{k} 0.85^{\,i-1}\, n_{s_i}}{\sum_{i=1}^{k} 0.85^{\,i-1}}
$$

At a fixed pace, $p$ is the number you set and $s = 1$.

## Finish

$$
L = \max(0,\; G - C)
$$

$$
D_\text{study} = \left\lceil \frac{L}{p} \right\rceil
\qquad
D = \left\lceil \frac{D_\text{study}}{\max\!\left(s,\ \tfrac{1}{7}\right)} \right\rceil
$$

$$
\text{finish date} = t + D
$$

## Shown as

| Setting | $D$ | Text |
|---|---|---|
| Days | any | $D$ days |
| Months | $D < 14$ | $D$ days |
| Months | $14 \le D < 70$ | $\operatorname{round}(D / 7)$ weeks |
| Months | $70 \le D < 730$ | $\operatorname{round}(D / 30.4)$ months |
| Months | $D \ge 730$ | $D / 365$ years (one decimal) |
