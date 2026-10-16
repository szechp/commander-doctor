package deckdoctor.bench;

/*
 * Phase 0 of the scenario bench (plan: ~/.claude/plans/so-beofre-we-go-validated-flute.md).
 *
 * One cell = a fresh 4-player game on a FIXED board recipe (identical for every
 * deck, no card-specific code), optional context card A put into play, optional
 * action B forced once, then the real engine plays one full round with Forge's
 * own PlayerControllerAi making every decision on every seat. The cell reports
 * a before/after metric vector; Python combines four cells into
 * I(A,B) = m(A+B) - m(A) - m(B) + m(empty).
 *
 * v2: two windows per cell. "metrics_imm" is taken once B and every trigger it
 * caused have resolved, before any player gets priority again (so no further AI
 * choices); "metrics" covers the full round as before. An A written as "~Name"
 * is a stand-in: the same card placed without entering and with all abilities
 * removed (Forge's RemoveAllAbilities), i.e. A's body without A's text.
 * "round_plays" lists the spells and activated abilities our AI chose during the
 * round, so Python can tell when A changed the AI's own choices.
 *
 * Input: TSV request file, one cell per line:
 *   id <TAB> seed <TAB> A-card-or-empty <TAB> B-card-or-empty <TAB> B-zone(hand|graveyard|battlefield) <TAB> B-ability-substring
 * Output: one "BENCH_RESULT {json}" line per cell on stdout.
 */

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.TreeMap;

import com.google.common.eventbus.Subscribe;

import forge.GuiDesktop;
import forge.StaticData;
import forge.ai.ComputerUtil;
import forge.ai.ComputerUtilCost;
import forge.ai.ComputerUtilMana;
import forge.ai.LobbyPlayerAi;
import forge.ai.PlayerControllerAi;
import forge.deck.Deck;
import forge.game.Game;
import forge.game.GameRules;
import forge.game.GameStage;
import forge.game.GameType;
import forge.game.Match;
import forge.game.card.Card;
import forge.game.card.CardFactory;
import forge.game.card.CounterEnumType;
import forge.game.event.GameEventAttackersDeclared;
import forge.game.event.GameEventCardChangeZone;
import forge.game.event.GameEventCardCounters;
import forge.game.event.GameEventPlayerDamaged;
import forge.game.event.GameEventScry;
import forge.game.event.GameEventSpellAbilityCast;
import forge.game.event.GameEventSurveil;
import forge.game.phase.PhaseHandler;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.player.PlayerView;
import forge.game.player.RegisteredPlayer;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;
import forge.gui.GuiBase;
import forge.item.IPaperCard;
import forge.item.PaperToken;
import forge.localinstance.properties.ForgePreferences.FPref;
import forge.model.FModel;
import forge.util.MyRandom;

public final class ScenarioBench {
    static final String RECIPE = "r1";
    static final String BENCH_VERSION = "v2";
    static final int MAX_STEPS = 20000;
    static final long CELL_MS = 30000;
    static final String[] BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest"};

    // ------------------------------------------------------------------ board helpers (ported from Forge's AITest)
    static Card createCard(String name, Player p) {
        IPaperCard pc = FModel.getMagicDb().getCommonCards().getCard(name);
        if (pc == null) {
            StaticData.instance().attemptToLoadCard(name);
            pc = FModel.getMagicDb().getCommonCards().getCard(name);
        }
        if (pc == null) throw new IllegalArgumentException("unavailable card: " + name);
        return Card.fromPaperCard(pc, p);
    }

    static Card add(String name, Player p, ZoneType zone) {
        Card c = createCard(name, p);
        c.setGameTimestamp(p.getGame().getNextTimestamp());
        p.getZone(zone).add(c);
        return c;
    }

    static Card addToken(String script, Player p) {
        PaperToken token = FModel.getMagicDb().getAllTokens().getToken(script);
        if (token == null) throw new IllegalStateException("missing token script " + script);
        Card c = CardFactory.getCard(token, p, p.getGame());
        c.setGameTimestamp(p.getGame().getNextTimestamp());
        p.getZone(ZoneType.Battlefield).add(c);
        return c;
    }

    /** Puts a permanent into play through the engine (ETB replacements and triggers run). */
    static Card putIntoPlay(String name, Player p) {
        Card c = add(name, p, ZoneType.Hand);
        Card moved = p.getGame().getAction().moveToPlay(c, p, null, null);
        moved.setSickness(false);
        return moved;
    }

    /** Resolve the stack and pending triggers with a hard cap (combos can loop forever). */
    static boolean settle(Game game, int cap) {
        int n = 0;
        game.getAction().checkStateEffects(true);
        game.getStack().addAllTriggeredAbilitiesToStack();
        while (!game.getStack().isEmpty() && !game.isGameOver()) {
            if (++n > cap) return false;
            game.getStack().resolveStack();
            game.getAction().checkStateEffects(true);
            game.getStack().addAllTriggeredAbilitiesToStack();
        }
        return true;
    }

    // ------------------------------------------------------------------ measurement
    static final class Observer {
        final Game game; final Player us;
        boolean on = false;
        boolean round = false;                               // past the immediate window: what our AI chose to play
        final List<String> roundPlays = new ArrayList<>();
        final Map<String, Integer> m = new TreeMap<>();
        final List<String> triggers = new ArrayList<>();
        final List<String> casts = new ArrayList<>();
        int oppActions = 0, oppAttacks = 0;
        Observer(Game game, Player us) { this.game = game; this.us = us; }
        void inc(String k, int v) { m.merge(k, v, Integer::sum); }
        boolean isUs(PlayerView pv) { return pv != null && pv.getId() == us.getId(); }

        @Subscribe public void cast(GameEventSpellAbilityCast e) {
            if (!on || game.getStack().isEmpty()) return;
            SpellAbility sa = game.getStack().peekAbility();
            Player who = sa.getActivatingPlayer();
            boolean mine = who != null && who.getId() == us.getId();
            String host = sa.getHostCard() == null ? "?" : sa.getHostCard().getName();
            if (sa.isTrigger()) {
                String mode = sa.getTrigger() == null ? "?" : String.valueOf(sa.getTrigger().getMode());
                triggers.add((mine ? "us:" : "opp:") + host + ":" + mode);
                return;
            }
            if (!mine) { if (sa.isSpell()) oppActions++; return; }
            if (round) roundPlays.add(host + ":" + (sa.isSpell() ? "cast" : String.valueOf(sa.getApi())));
            if (sa.isSpell()) {
                if (sa.isCopied()) inc("spells_copied", 1); else { inc("spells_cast", 1); casts.add(host); }
            }
        }

        @Subscribe public void zone(GameEventCardChangeZone e) {
            if (!on || e.card() == null) return;
            ZoneType from = e.from() == null ? null : e.from().zoneType();
            ZoneType to = e.to() == null ? null : e.to().zoneType();
            PlayerView fromP = e.from() == null ? null : e.from().player();
            PlayerView toP = e.to() == null ? null : e.to().player();
            boolean creature = e.card().getCurrentState() != null && e.card().getCurrentState().isCreature();
            if (from == ZoneType.Library && to == ZoneType.Hand && isUs(toP)) inc("cards_drawn", 1);
            if (from == ZoneType.Hand && to == ZoneType.Graveyard && isUs(fromP)) inc("discards", 1);
            if (to == ZoneType.Battlefield && isUs(toP) && e.card().isToken()) {
                inc("tokens_created", 1);
                if (e.card().getName().contains("Treasure")) inc("treasures_created", 1);
            }
            if (from == ZoneType.Battlefield && to == ZoneType.Graveyard && creature) {
                inc(isUs(fromP) ? "our_creatures_died" : "opp_creatures_died", 1);
            }
            if (from == ZoneType.Battlefield && fromP != null && !isUs(fromP)) inc("opp_permanents_left", 1);
            if (from == ZoneType.Library && to == ZoneType.Graveyard && isUs(toP)) inc("milled", 1);
        }

        @Subscribe public void damage(GameEventPlayerDamaged e) {
            if (!on || e.target() == null || isUs(e.target())) return;
            if (e.combat()) inc("opp_life_lost_combat_dmg", e.amount());
        }

        @Subscribe public void counters(GameEventCardCounters e) {
            if (!on || e.card() == null || e.type() != CounterEnumType.P1P1) return;
            if (isUs(e.card().getController()) && e.newValue() > e.oldValue()) inc("p1p1_counters_placed", e.newValue() - e.oldValue());
        }

        @Subscribe public void scry(GameEventScry e) { if (on && isUs(e.player())) inc("scry_events", 1); }
        @Subscribe public void surveil(GameEventSurveil e) { if (on && isUs(e.player())) inc("surveil_events", 1); }

        @Subscribe public void attacks(GameEventAttackersDeclared e) {
            if (on && e.player() != null && !isUs(e.player()) && e.attackersMap() != null && !e.attackersMap().isEmpty()) oppAttacks++;
        }
    }

    static int manaEstimate(Player p) {
        // checkPlayable=true: a tapped land can't be activated, so it no longer counts
        // the estimate already includes floating mana in the pool -- don't add it twice
        return ComputerUtilMana.getAvailableManaEstimate(p, true);
    }

    /** Event counts plus the state-derived metrics (life, mana) at this moment. */
    static Map<String, Integer> derive(Map<String, Integer> events, Game game, Player us, Map<Integer, Integer> life0, int netMana) {
        Map<String, Integer> m = new TreeMap<>(events);
        int oppLost = 0;
        for (Player p : game.getPlayers()) {
            if (p == us) continue;
            oppLost += life0.get(p.getId()) - p.getLife();
        }
        int combat = m.getOrDefault("opp_life_lost_combat_dmg", 0);
        m.remove("opp_life_lost_combat_dmg");
        m.put("opp_life_lost", oppLost);
        m.put("opp_life_lost_combat", combat);
        m.put("opp_life_lost_noncombat", oppLost - combat);
        m.put("our_life_change", us.getLife() - life0.get(us.getId()));
        m.put("net_mana_after_b", netMana);
        return m;
    }

    /** A's body without A's text: placed straight onto the battlefield (no ETB), then loses all abilities. */
    static void putStandIn(String name, Player p) {
        Card c = add(name, p, ZoneType.Battlefield);
        long ts = p.getGame().getNextTimestamp();
        c.addChangedCardKeywords(List.of(), List.of(), true, ts, null);
        c.addChangedCardTraits(List.of(), List.of(), List.of(), List.of(), t -> true, ts, 0);
    }

    // ------------------------------------------------------------------ one cell
    static Map<String, Object> runCell(String id, long seed, String aName, String bName, String bZone, String bAbility) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", id); out.put("seed", seed); out.put("recipe", RECIPE); out.put("bench", BENCH_VERSION);
        out.put("a", aName); out.put("b", bName); out.put("b_zone", bZone); out.put("b_ability", bAbility);
        long t0 = System.nanoTime();
        Game game = null;
        try {
            MyRandom.setRandom(new Random(seed));
            List<RegisteredPlayer> players = new ArrayList<>();
            for (int i = 0; i < 4; i++) {
                players.add(new RegisteredPlayer(new Deck()).setPlayer(new LobbyPlayerAi(i == 0 ? "us" : "opp" + i, null)));
            }
            GameRules rules = new GameRules(GameType.Commander);
            rules.setAppliedVariants(EnumSet.of(GameType.Commander));
            Match match = new Match(rules, players, "scenario-bench");
            game = new Game(players, rules, match);
            Player us = game.getPlayers().get(0);
            game.setAge(GameStage.Play);
            game.getPhaseHandler().devModeSet(PhaseType.MAIN1, us);
            game.getPhaseHandler().onStackResolved();

            // ---- fixed board recipe r1 (identical for every deck)
            for (Player p : game.getPlayers()) { p.setStartingLife(40); p.setLife(40, null); }
            for (String b : BASICS) { add(b, us, ZoneType.Battlefield); add(b, us, ZoneType.Battlefield); }
            for (int i = 0; i < 3; i++) addToken("c_1_1_shapeshifter_changeling", us).setSickness(false);
            add("Spellbook", us, ZoneType.Battlefield);
            add("Plains", us, ZoneType.Graveyard); add("Island", us, ZoneType.Graveyard);
            add("Grizzly Bears", us, ZoneType.Graveyard); add("Runeclaw Bear", us, ZoneType.Graveyard);
            add("Mountain", us, ZoneType.Hand);
            for (int i = 0; i < 30; i++) add(BASICS[i % 5], us, ZoneType.Library);
            for (Player o : game.getPlayers()) {
                if (o == us) continue;
                add("Ornithopter", o, ZoneType.Battlefield).setTapped(true);
                add("Spellbook", o, ZoneType.Battlefield);
                add("Leyline of Anticipation", o, ZoneType.Battlefield);
                for (int i = 0; i < 3; i++) add(BASICS[i], o, ZoneType.Hand);
                for (int i = 0; i < 30; i++) add(BASICS[i % 5], o, ZoneType.Library);
            }

            // ---- B placement (battlefield B is part of the board for its cells)
            Card bCard = null;
            if (!bName.isEmpty()) {
                switch (bZone) {
                    case "battlefield" -> bCard = putIntoPlay(bName, us);
                    case "graveyard" -> bCard = add(bName, us, ZoneType.Graveyard);
                    default -> bCard = add(bName, us, ZoneType.Hand);
                }
                if (!settle(game, 500)) { out.put("status", "looped"); out.put("reason", "B placement loop"); return finish(out, t0); }
                for (Card c : us.getCardsIn(ZoneType.Battlefield)) { c.setTapped(false); c.setSickness(false); }
            }

            // ---- context A
            boolean standIn = aName.startsWith("~");
            if (standIn) aName = aName.substring(1);
            if (!aName.isEmpty()) {
                Card probe = createCard(aName, us);
                if (standIn) {
                    // a nonpermanent has no body: its stand-in is no context at all
                    if (probe.isPermanent()) putStandIn(aName, us);
                    out.put("stand_in", probe.isPermanent() ? "abilities removed" : "none (nonpermanent)");
                } else if (probe.isPermanent()) {
                    putIntoPlay(aName, us);
                } else {
                    // instants/sorceries as context: cast with temporary extra lands, then remove them
                    List<Card> temp = new ArrayList<>();
                    for (String b : BASICS) for (int i = 0; i < 3; i++) temp.add(add(b, us, ZoneType.Battlefield));
                    Card a = add(aName, us, ZoneType.Hand);
                    SpellAbility sa = firstSpell(a, us);
                    if (sa == null || !castForced(us, sa)) { out.put("status", "not_playable"); out.put("reason", "context A could not be cast"); return finish(out, t0); }
                    if (!settle(game, 500)) { out.put("status", "looped"); out.put("reason", "context A loop"); return finish(out, t0); }
                    for (Card c : temp) game.getAction().exile(c, null, null);
                }
                if (!settle(game, 500)) { out.put("status", "looped"); out.put("reason", "context A triggers loop"); return finish(out, t0); }
                for (Card c : us.getCardsIn(ZoneType.Battlefield)) { c.setTapped(false); c.setSickness(false); }
                us.getManaPool().clearPool(false);
            }
            us.setLandsPlayedThisTurn(1);

            // ---- snapshot S0 and start measuring
            Observer obs = new Observer(game, us);
            game.subscribeToEvents(obs);
            Map<Integer, Integer> life0 = new LinkedHashMap<>();
            for (Player p : game.getPlayers()) life0.put(p.getId(), p.getLife());
            int mana0 = manaEstimate(us);
            obs.on = true;

            // ---- force action B
            int manaB = mana0;
            if (bCard != null) {
                SpellAbility sa = pickAbility(bCard, us, bZone, bAbility);
                if (sa == null) { out.put("status", "not_playable"); out.put("reason", "no matching playable ability"); return finish(out, t0); }
                out.put("b_sa", sa.toString());
                if (!ComputerUtilCost.canPayCost(sa, us, false)) { out.put("status", "not_playable"); out.put("reason", "cannot pay"); return finish(out, t0); }
                boolean ok;
                if (sa.isManaAbility()) ok = ComputerUtil.playNoStack(us, sa, game, true);
                else ok = castForced(us, sa);
                if (!ok) { out.put("status", "not_playable"); out.put("reason", "engine refused (targets/costs)"); return finish(out, t0); }
                // resolve B and everything it triggers without handing out priority: no further AI plays yet
                if (!settle(game, 500)) { out.put("status", "looped"); out.put("reason", "B resolution loop"); return finish(out, t0); }
                manaB = manaEstimate(us);
            }
            // ---- immediate window: B and its triggers only
            out.put("metrics_imm", derive(obs.m, game, us, life0, manaB - mana0));
            obs.round = true;

            // ---- run the round until our next turn's main phase
            PhaseHandler ph = game.getPhaseHandler();
            int startTurn = ph.getTurn();
            int steps = 0;
            long deadline = System.currentTimeMillis() + CELL_MS;
            while (!game.isGameOver()) {
                if (ph.getTurn() > startTurn && ph.getPlayerTurn() == us && ph.is(PhaseType.MAIN1)) break;
                if (++steps > MAX_STEPS) { out.put("status", "looped"); out.put("reason", "step cap"); return finish(out, t0); }
                if (System.currentTimeMillis() > deadline) { out.put("status", "timeout"); return finish(out, t0); }
                ph.mainLoopStep();
            }
            obs.on = false;

            // ---- metrics (full round)
            out.put("mana_s0_sb", List.of(mana0, manaB));
            out.put("metrics", derive(obs.m, game, us, life0, manaB - mana0));
            out.put("triggers", obs.triggers);
            out.put("our_casts", obs.casts);
            out.put("round_plays", obs.roundPlays);
            out.put("opp_spells", obs.oppActions);
            out.put("opp_attacks", obs.oppAttacks);
            out.put("steps", steps);
            boolean lethal = game.isGameOver();
            for (Player p : game.getPlayers()) if (p.getLife() <= 0) lethal = true;
            out.put("status", lethal ? "lethal" : "ok");
        } catch (Throwable ex) {
            out.put("status", "error");
            out.put("reason", ex.getClass().getSimpleName() + ": " + String.valueOf(ex.getMessage()));
        }
        return finish(out, t0);
    }

    static Map<String, Object> finish(Map<String, Object> out, long t0) {
        out.put("ms", Math.round((System.nanoTime() - t0) / 1e5) / 10.0);
        return out;
    }

    static SpellAbility firstSpell(Card c, Player p) {
        for (SpellAbility sa : c.getAllPossibleAbilities(p, true)) {
            if (sa.isSpell()) { sa.setActivatingPlayer(p); return sa; }
        }
        return null;
    }

    static SpellAbility pickAbility(Card c, Player p, String zone, String needle) {
        for (SpellAbility sa : c.getAllPossibleAbilities(p, true)) {
            sa.setActivatingPlayer(p);
            // a named ability (e.g. "Cycling") may be a spell or an activated ability from any zone;
            // without a name: activated abilities on the battlefield, spells from hand/graveyard
            if (needle.isEmpty() && (zone.equals("battlefield") ? sa.isSpell() : !sa.isSpell())) continue;
            if (!needle.isEmpty() && !sa.toString().toLowerCase().contains(needle.toLowerCase())
                    && (sa.getDescription() == null || !sa.getDescription().toLowerCase().contains(needle.toLowerCase()))) continue;
            return sa;
        }
        return null;
    }

    /** Put the ability on the stack with Forge's AI choosing targets/modes/costs (mandatory targets). */
    static boolean castForced(Player us, SpellAbility sa) {
        PlayerControllerAi ctrl = (PlayerControllerAi) us.getController();
        return ComputerUtil.handlePlayingSpellAbility(us, sa, s -> ctrl.chooseTargetsFor(s));
    }

    // ------------------------------------------------------------------ JSON (no dependency)
    static String json(Object o) {
        if (o == null) return "null";
        if (o instanceof String s) return '"' + s.replace("\\", "\\\\").replace("\"", "\\\"").replaceAll("[\\x00-\\x1f]", " ") + '"';
        if (o instanceof Number || o instanceof Boolean) return String.valueOf(o);
        if (o instanceof Map<?, ?> map) {
            StringBuilder sb = new StringBuilder("{");
            for (Map.Entry<?, ?> e : map.entrySet()) { if (sb.length() > 1) sb.append(','); sb.append(json(String.valueOf(e.getKey()))).append(':').append(json(e.getValue())); }
            return sb.append('}').toString();
        }
        if (o instanceof List<?> list) {
            StringBuilder sb = new StringBuilder("[");
            for (Object x : list) { if (sb.length() > 1) sb.append(','); sb.append(json(x)); }
            return sb.append(']').toString();
        }
        return json(String.valueOf(o));
    }

    public static void main(String[] args) throws Exception {
        Thread.currentThread().setName("Game-scenario-bench");   // GameAction.invoke runs inline on "Game*" threads
        GuiBase.setInterface(new GuiDesktop());
        FModel.initialize(null, prefs -> {
            prefs.setPref(FPref.LOAD_CARD_SCRIPTS_LAZILY, false);
            prefs.setPref(FPref.UI_LANGUAGE, "en-US");
            return null;
        });
        for (String line : Files.readAllLines(Path.of(args[0]))) {
            if (line.isBlank() || line.startsWith("#")) continue;
            String[] f = line.split("\t", -1);
            Map<String, Object> r = runCell(f[0], Long.parseLong(f[1]), f[2], f.length > 3 ? f[3] : "",
                    f.length > 4 ? f[4] : "hand", f.length > 5 ? f[5] : "");
            System.out.println("BENCH_RESULT " + json(r));
            System.out.flush();
        }
        System.exit(0);
    }
}
