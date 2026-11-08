# Game 24 – three realms with a market (Claude as the three sovereigns)

Realms: 26 Aurelia (F+ W= S-), 27 Brenna (F- W+ S=), 28 Corvara (F= W- S+). Seed 0.

## Sovereign rules used (draft for the automatic sovereign)

1. Grant a petition when the treasury still covers upkeep + salaries at the asked rate.
2. Winter food check: refuse any order that would empty the granary before spring
   (store + winter harvest - consumption over the winter months left < 0).
3. No claims in winter: clearing waits until spring, gold is kept for the market.
4. Approve trades the Treasurer asks when the cost check passes.

## Turn log

- T1 (Jan): Aurelia's Treasurer buys wood unprompted (firewood 50/month vs 24 made). Architect wanted 13 farmers off the fields in winter (excluded, rule 2) and 4 claims (excluded, rule 3).
  Brenna buys 6 lots of food (the whole start stock) and 1 of wood. Corvara: empty plan; its Treasurer's report leaked a retry ("Let me recompute the report...").
- T2 (Feb): Aurelia's Chancellor adds a quarry on poor stone land (stone upkeep 12 > 6 made): approved.
  Brenna (food poor, wood rich, 20 gold) did not think of selling wood; a sovereign directive ("sell the wood the fire does not need") made the Treasurer sell 1 lot. Brenna's Chancellor proposed 66 workers of 60 (refused by the check; excluded).
  Corvara: reduced ration for Feb-Mar (spring would not cover), petition tax 8 granted; Treasurer: "the food market is empty, buying would bring nothing" (read the stock).
  Rule 5 (new): when gold is short and a good is clearly above its needs, direct the Treasurer to sell it.
- T3 (Mar): wood asked 4 lots, 2 in the warehouse: split 1 + 1 (pro rata works); Brenna's wood sold and paid (13). Brenna's food purchase filled 0 of 1 (no food on sale: nobody sells food yet). Corvara: normal ration granted (petition) + feast 20. All three through the first winter without hunger.
  Corvara's Architect extended the fields zone to claim from April; Treasurers now quote the market ("il mercato del cibo è vuoto").
- T4 (Apr): nobody sells food: Aurelia (food rich) comes out of winter with 281 and no surplus yet. Brenna (food poor) asks the reduced ration in spring (770 harvest vs 880 eaten). Brenna's petition (tax 5) refused: with 39 gold it could no longer buy grain (rule 1 the other way). Claims approved in spring (Aurelia 2, Corvara 4).
- T5 (May): wood is short everywhere and nobody sells it: Aurelia and Corvara ask for it, the warehouse is empty; Brenna (wood rich) keeps its surplus. Corvara's Treasurer proposed tax 5 (petition) with income below upkeep + salaries: refused. Brenna asked the full ration back (petition): refused, the May harvest does not carry it; a feast of 10 instead (Treasurer's idea).
  Rule 6 (new): refuse a tax cut that makes income lower than upkeep + salaries.
  Corvara's Treasurer tried to propose a farm (NOT_ROLE_ACTION, discarded).
- T6 (Jun): Aurelia (stone poor, 37 left, upkeep 14, made 6): its Treasurer did not think of buying stone (and proposed orders outside its role); directive -> bought 2 lots (100 stone, 44 gold). Corvara (stone rich): directive -> sold 1 lot; the first 10 units of it were bought the same month (paid 3), the rest waits. Corvara's claims were left out by the directive ("no claims this month").
  Brenna: the Architect moved 6 farmers to wood and stone in a food-poor realm; excluded (rule 2). Petition (normal ration, third time) granted: summer carries it.
  Balance remark: for a wood-rich, food-poor realm, a worker on wood (9 wood = about 2.7 gold at 15/lot) earns about what a farmer makes (14 food = about 2.8 gold at 10/lot): specialising does not pay at the start prices.
  Rule 7 (new): when a good covers less than 3 months of its upkeep and the market holds it, direct the Treasurer to buy.
- T7 (Jul): everybody asks for wood (Aurelia 1, Brenna 1, Corvara 2 lots), the warehouse holds none: nothing filled, the price will rise. Brenna (wood rich) wanted to buy wood although its sawmill and stock cover the winter: excluded; its petition (tax 6) refused (income would equal costs, gold needed for winter grain). Corvara put the first food of the game on sale (1 lot).
- T8 (Aug): a world shortage of wood: every realm keeps 4 men at the sawmill. Corvara (wood poor) has 49 for a winter needing 260. Directive to Brenna (wood rich, 6 empty sawmill jobs): fill the sawmill and sell -> 7 woodmen, 1 lot on sale; a new farm with 18 empty farm jobs excluded. Brenna's petition (tax 6) granted: income equals costs (rule 6: refuse only when below).
  Corvara sold its second lot of food to save gold for wood; Aurelia's feast leaves 0 gold before the trade fails.
- T9 (Sep): DEFECT found and fixed (dbdaca4): 1 lot of food asked by Brenna (2) and Corvara (2) went to nobody (pro rata rounded down to 0 + 0). Now the leftover lots go to the largest remainders. Replay of game 24 unchanged.
  Corvara's Treasurer wanted to buy back its own food on sale (98 in the warehouse were its own two lots): paying the margin twice. Excluded. Design question for the user: refuse buying a good you have on sale, or let a seller withdraw?
  Brenna's Chancellor added a house with 14 free places and 58 gold before winter grain: excluded. Aurelia gold 6: no grain can be bought for its own winter.
- T10 (Oct): nobody has food to sell. Aurelia (food rich, 16 per farmer) reaches 731 in autumn but its Treasurer counts that its own winter will not be covered (423 a month against 918 eaten). With food levels 14/15/16 and the winter halving every harvest, no realm makes a surplus: the food market has no supply (the lab's granary at 17-18 did sell).
  Corvara (wood poor) solves its firewood by felling 2 forest tiles (10 wood per worker-month) with 3 clearing hands: the land offers a way the market does not.
- T11 (Nov): the warehouse holds 48 food (the rest of Corvara's lot after spoilage): less than a lot, nobody can buy it and it will rot. Design remark: remnants under a lot are stuck.
  Aurelia's Chancellor moved 13 farmers to the sawmill and the quarry at the autumn harvest (40/10/15): excluded (rule 2), with a feast that would leave 8 gold.
  Corvara: reduced ration from November (its Treasurer counted a famine in March otherwise).
