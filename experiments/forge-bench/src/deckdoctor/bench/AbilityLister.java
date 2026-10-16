package deckdoctor.bench;

/*
 * Lists what each card can do as action B on the bench board: for every zone
 * (hand, battlefield, graveyard) every ability Forge reports for the card there
 * (getAllPossibleAbilities, the same call ScenarioBench.pickAbility uses), with
 * whether it is playable on the bare board, plus the card's trigger modes (for
 * the "never fired = untested" report).
 *
 * Input: a file with one card name per line. Output: one "ABILITIES {json}" line per card.
 */

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import forge.GuiDesktop;
import forge.ai.LobbyPlayerAi;
import forge.deck.Deck;
import forge.game.Game;
import forge.game.GameRules;
import forge.game.GameStage;
import forge.game.GameType;
import forge.game.Match;
import forge.game.card.Card;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.player.RegisteredPlayer;
import forge.game.spellability.SpellAbility;
import forge.game.trigger.Trigger;
import forge.game.zone.ZoneType;
import forge.gui.GuiBase;
import forge.localinstance.properties.ForgePreferences.FPref;
import forge.model.FModel;

public final class AbilityLister {
    public static void main(String[] args) throws Exception {
        Thread.currentThread().setName("Game-ability-lister");
        GuiBase.setInterface(new GuiDesktop());
        FModel.initialize(null, prefs -> {
            prefs.setPref(FPref.LOAD_CARD_SCRIPTS_LAZILY, false);
            prefs.setPref(FPref.UI_LANGUAGE, "en-US");
            return null;
        });
        for (String name : Files.readAllLines(Path.of(args[0]))) {
            if (name.isBlank()) continue;
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("card", name);
            try {
                Map<String, Object> zones = new LinkedHashMap<>();
                List<String> triggers = new ArrayList<>();
                for (String zone : List.of("hand", "battlefield", "graveyard")) {
                    Game game = board();
                    Player us = game.getPlayers().get(0);
                    ZoneType z = zone.equals("hand") ? ZoneType.Hand : zone.equals("battlefield") ? ZoneType.Battlefield : ZoneType.Graveyard;
                    Card c = ScenarioBench.add(name, us, z);
                    c.setSickness(false);
                    List<Map<String, Object>> abs = new ArrayList<>();
                    List<SpellAbility> playable = c.getAllPossibleAbilities(us, true);
                    // all abilities, not just those usable on the bare board: a conditional one
                    // ("only if you created a token this turn") is exactly what another card can enable
                    for (SpellAbility sa : c.getAllPossibleAbilities(us, false)) {
                        sa.setActivatingPlayer(us);
                        Map<String, Object> a = new LinkedHashMap<>();
                        a.put("playable", playable.contains(sa));
                        a.put("zone_restriction", String.valueOf(sa.getRestrictions() == null ? null : sa.getRestrictions().getZone()));
                        a.put("spell", sa.isSpell());
                        a.put("mana", sa.isManaAbility());
                        a.put("api", String.valueOf(sa.getApi()));
                        a.put("cost", sa.getPayCosts() == null ? "" : sa.getPayCosts().toSimpleString());
                        a.put("desc", String.valueOf(sa.getDescription()));
                        a.put("str", sa.toString());
                        abs.add(a);
                    }
                    zones.put(zone, abs);
                    if (zone.equals("battlefield")) {
                        for (Trigger t : c.getTriggers()) triggers.add(String.valueOf(t.getMode()));
                    }
                }
                out.put("zones", zones);
                out.put("trigger_modes", triggers);
                out.put("status", "ok");
            } catch (Throwable ex) {
                out.put("status", "error");
                out.put("reason", ex.getClass().getSimpleName() + ": " + ex.getMessage());
            }
            System.out.println("ABILITIES " + ScenarioBench.json(out));
            System.out.flush();
        }
        System.exit(0);
    }

    /** The parts of board r1 that decide whether an ability is playable: our main phase, 10 basics, fodder, a graveyard. */
    static Game board() {
        List<RegisteredPlayer> players = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            players.add(new RegisteredPlayer(new Deck()).setPlayer(new LobbyPlayerAi(i == 0 ? "us" : "opp" + i, null)));
        }
        GameRules rules = new GameRules(GameType.Commander);
        rules.setAppliedVariants(EnumSet.of(GameType.Commander));
        Game game = new Game(players, rules, new Match(rules, players, "ability-lister"));
        Player us = game.getPlayers().get(0);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, us);
        game.getPhaseHandler().onStackResolved();
        for (String b : ScenarioBench.BASICS) { ScenarioBench.add(b, us, ZoneType.Battlefield); ScenarioBench.add(b, us, ZoneType.Battlefield); }
        for (int i = 0; i < 3; i++) ScenarioBench.addToken("c_1_1_shapeshifter_changeling", us).setSickness(false);
        ScenarioBench.add("Spellbook", us, ZoneType.Battlefield);
        ScenarioBench.add("Plains", us, ZoneType.Graveyard); ScenarioBench.add("Island", us, ZoneType.Graveyard);
        ScenarioBench.add("Grizzly Bears", us, ZoneType.Graveyard); ScenarioBench.add("Runeclaw Bear", us, ZoneType.Graveyard);
        ScenarioBench.add("Mountain", us, ZoneType.Hand);
        us.setLandsPlayedThisTurn(1);
        return game;
    }
}
