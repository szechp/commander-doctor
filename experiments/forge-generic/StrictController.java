package deckdoctor.generic;
import com.google.common.collect.ListMultimap;
import com.google.common.collect.Lists;
import com.google.common.collect.Multimap;
import forge.LobbyPlayer;
import forge.card.ColorSet;
import forge.card.ICardFace;
import forge.card.mana.ManaCost;
import forge.card.mana.ManaCostShard;
import forge.deck.Deck;
import forge.deck.DeckSection;
import forge.game.*;
import forge.game.GameOutcome.AnteResult;
import forge.game.ability.AbilityUtils;
import forge.game.ability.effects.RollDiceEffect;
import forge.game.card.*;
import forge.game.combat.Combat;
import forge.game.cost.*;
import forge.game.keyword.KeywordInterface;
import forge.game.mana.Mana;
import forge.game.mana.ManaConversionMatrix;
import forge.game.mana.ManaCostBeingPaid;
import forge.game.replacement.ReplacementEffect;
import forge.game.spellability.*;
import forge.game.staticability.StaticAbility;
import forge.game.trigger.WrappedAbility;
import forge.game.zone.PlayerZone;
import forge.game.zone.ZoneType;
import forge.item.PaperCard;
import forge.util.ITriggerEvent;
import forge.util.collect.FCollectionView;
import org.apache.commons.lang3.tuple.ImmutablePair;
import org.apache.commons.lang3.tuple.Pair;
import java.util.Arrays;
import java.util.Collection;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Predicate;
import java.util.stream.Collectors;
import forge.game.player.*;
public class StrictController extends PlayerController {
protected UnsupportedOperationException unsupported(String decision) { return new UnsupportedOperationException(decision); }
public StrictController(Game g, Player p, LobbyPlayer l) { super(g,p,l); }
@Override public SpellAbility getAbilityToPlay(Card hostCard, List<SpellAbility> abilities, ITriggerEvent triggerEvent) { throw unsupported("getAbilityToPlay"); }
@Override public void playSpellAbilityNoStack(SpellAbility effectSA, boolean mayChoseNewTargets) { throw unsupported("playSpellAbilityNoStack"); }
@Override public List<SpellAbility> orderSimultaneousSa(List<SpellAbility> activePlayerSAs) { throw unsupported("orderSimultaneousSa"); }
@Override public void orderAndPlaySimultaneousSa(List<SpellAbility> activePlayerSAs) { throw unsupported("orderAndPlaySimultaneousSa"); }
@Override public boolean playTrigger(Card host, WrappedAbility wrapperAbility, boolean isMandatory) { throw unsupported("playTrigger"); }
@Override public boolean playSaFromPlayEffect(SpellAbility tgtSA) { throw unsupported("playSaFromPlayEffect"); }
@Override public List<PaperCard> sideboard(final Deck deck, GameType gameType, String message) { throw unsupported("sideboard"); }
@Override public List<PaperCard> chooseCardsYouWonToAddToDeck(List<PaperCard> losses) { throw unsupported("chooseCardsYouWonToAddToDeck"); }
@Override public Map<Card, Integer> assignCombatDamage(Card attacker, CardCollectionView blockers, CardCollectionView remaining, int damageDealt, GameEntity defender, boolean overrideOrder) { throw unsupported("assignCombatDamage"); }
@Override public Map<GameEntity, Integer> divideShield(Card effectSource, Map<GameEntity, Integer> affected, int shieldAmount) { throw unsupported("divideShield"); }
@Override public Map<Byte, Integer> specifyManaCombo(SpellAbility sa, ColorSet colorSet, int manaAmount, boolean different) { throw unsupported("specifyManaCombo"); }
@Override public CardCollectionView choosePermanentsToSacrifice(SpellAbility sa, int min, int max, CardCollectionView validTargets, String message) { throw unsupported("choosePermanentsToSacrifice"); }
@Override public CardCollectionView choosePermanentsToDestroy(SpellAbility sa, int min, int max, CardCollectionView validTargets, String message) { throw unsupported("choosePermanentsToDestroy"); }
@Override public Integer announceRequirements(SpellAbility ability, int min, int max, String announce) { throw unsupported("announceRequirements"); }
@Override public TargetChoices chooseNewTargetsFor(SpellAbility ability, Predicate<GameObject> filter, boolean optional) { throw unsupported("chooseNewTargetsFor"); }
@Override public boolean chooseTargetsFor(SpellAbility currentAbility) { throw unsupported("chooseTargetsFor"); }
@Override public Pair<SpellAbilityStackInstance, GameObject> chooseTarget(SpellAbility sa, List<Pair<SpellAbilityStackInstance, GameObject>> allTargets) { throw unsupported("chooseTarget"); }
@Override public boolean helpPayForAssistSpell(ManaCostBeingPaid cost, SpellAbility sa, int max, int requested) { throw unsupported("helpPayForAssistSpell"); }
@Override public Player choosePlayerToAssistPayment(FCollectionView<Player> optionList, SpellAbility sa, String title, int max) { throw unsupported("choosePlayerToAssistPayment"); }
@Override public CardCollectionView chooseCardsForEffect(CardCollectionView sourceList, SpellAbility sa, String title, int min, int max, boolean isOptional, Map<String, Object> params) { throw unsupported("chooseCardsForEffect"); }
@Override public CardCollection chooseCardsForEffectMultiple(Map<String, CardCollection> validMap, SpellAbility sa, String title, boolean isOptional) { throw unsupported("chooseCardsForEffectMultiple"); }
@Override public <T extends GameEntity> T chooseSingleEntityForEffect(FCollectionView<T> optionList, DelayedReveal delayedReveal, SpellAbility sa, String title, boolean isOptional, Player relatedPlayer, Map<String, Object> params) { throw unsupported("chooseSingleEntityForEffect"); }
@Override public <T extends GameEntity> List<T> chooseEntitiesForEffect(FCollectionView<T> optionList, int min, int max, DelayedReveal delayedReveal, SpellAbility sa, String title, Player relatedPlayer, Map<String, Object> params) { throw unsupported("chooseEntitiesForEffect"); }
@Override public List<SpellAbility> chooseSpellAbilitiesForEffect(List<SpellAbility> spells, SpellAbility sa, String title, int num, Map<String, Object> params) { throw unsupported("chooseSpellAbilitiesForEffect"); }
@Override public SpellAbility chooseSingleSpellForEffect(List<SpellAbility> spells, SpellAbility sa, String title, Map<String, Object> params) { throw unsupported("chooseSingleSpellForEffect"); }
@Override public boolean confirmAction(SpellAbility sa, PlayerActionConfirmMode mode, String message, List<String> options, Card cardToShow, Map<String, Object> params) { throw unsupported("confirmAction"); }
@Override public boolean confirmBidAction(SpellAbility sa, PlayerActionConfirmMode bidlife, String string, int bid, Player winner) { throw unsupported("confirmBidAction"); }
@Override public boolean confirmReplacementEffect(ReplacementEffect replacementEffect, SpellAbility effectSA, GameEntity affected, String question) { throw unsupported("confirmReplacementEffect"); }
@Override public boolean confirmStaticApplication(Card hostCard, PlayerActionConfirmMode mode, String message, String logic) { throw unsupported("confirmStaticApplication"); }
@Override public boolean confirmTrigger(WrappedAbility sa) { throw unsupported("confirmTrigger"); }
@Override public List<Card> exertAttackers(List<Card> attackers) { throw unsupported("exertAttackers"); }
@Override public List<Card> enlistAttackers(List<Card> attackers) { throw unsupported("enlistAttackers"); }
@Override public void declareAttackers(Player attacker, Combat combat) { throw unsupported("declareAttackers"); }
@Override public void declareBlockers(Player defender, Combat combat) { throw unsupported("declareBlockers"); }
@Override public CardCollection orderBlockers(Card attacker, CardCollection blockers) { throw unsupported("orderBlockers"); }
@Override public CardCollection orderBlocker(final Card attacker, final Card blocker, final CardCollection oldBlockers) { throw unsupported("orderBlocker"); }
@Override public CardCollection orderAttackers(Card blocker, CardCollection attackers) { throw unsupported("orderAttackers"); }
@Override public void reveal(CardCollectionView cards, ZoneType zone, Player owner, String messagePrefix, boolean addMsgSuffix) { throw unsupported("reveal"); }
@Override public void reveal(List<CardView> cards, ZoneType zone, PlayerView owner, String messagePrefix, boolean addMsgSuffix) { throw unsupported("reveal"); }
@Override public void notifyOfValue(SpellAbility saSource, GameObject realtedTarget, String value) { throw unsupported("notifyOfValue"); }
@Override public ImmutablePair<CardCollection, CardCollection> arrangeForScry(CardCollection topN) { throw unsupported("arrangeForScry"); }
@Override public ImmutablePair<CardCollection, CardCollection> arrangeForSurveil(CardCollection topN) { throw unsupported("arrangeForSurveil"); }
@Override public boolean willPutCardOnTop(Card c) { throw unsupported("willPutCardOnTop"); }
@Override public CardCollectionView orderMoveToZoneList(CardCollectionView cards, ZoneType destinationZone, SpellAbility source) { throw unsupported("orderMoveToZoneList"); }
@Override public CardCollectionView chooseCardsToDiscardFrom(Player playerDiscard, SpellAbility sa, CardCollection validCards, int min, int max, CardCollectionView visibleToChooser) { throw unsupported("chooseCardsToDiscardFrom"); }
@Override public CardCollectionView chooseCardsToDiscardUnlessType(int min, CardCollectionView hand, String[] unlessTypes, SpellAbility sa) { throw unsupported("chooseCardsToDiscardUnlessType"); }
@Override public CardCollectionView chooseCardsToDiscardToMaximumHandSize(int numDiscard) { throw unsupported("chooseCardsToDiscardToMaximumHandSize"); }
@Override public CardCollectionView chooseCardsToDelve(int genericAmount, CardCollection grave) { throw unsupported("chooseCardsToDelve"); }
@Override public Map<Card, ManaCostShard> chooseCardsForConvokeOrImprovise(SpellAbility sa, ManaCost manaCost, CardCollectionView untappedCards, boolean artifacts, boolean creatures, Integer maxReduction) { throw unsupported("chooseCardsForConvokeOrImprovise"); }
@Override public List<Card> chooseCardsForSplice(SpellAbility sa, List<Card> cards) { throw unsupported("chooseCardsForSplice"); }
@Override public CardCollectionView chooseCardsToRevealFromHand(int min, int max, CardCollectionView valid) { throw unsupported("chooseCardsToRevealFromHand"); }
@Override public List<SpellAbility> chooseSaToActivateFromOpeningHand(List<SpellAbility> usableFromOpeningHand) { throw unsupported("chooseSaToActivateFromOpeningHand"); }
@Override public Player chooseStartingPlayer(boolean isFirstGame) { throw unsupported("chooseStartingPlayer"); }
@Override public PlayerZone chooseStartingHand(List<PlayerZone> zones) { throw unsupported("chooseStartingHand"); }
@Override public Mana chooseManaFromPool(List<Mana> manaChoices) { throw unsupported("chooseManaFromPool"); }
@Override public String chooseSomeType(String kindOfType, SpellAbility sa, Collection<String> validTypes, boolean isOptional) { throw unsupported("chooseSomeType"); }
@Override public String chooseSector(Card assignee, String ai, List<String> sectors) { throw unsupported("chooseSector"); }
@Override public List<Card> chooseContraptionsToCrank(List<Card> contraptions) { throw unsupported("chooseContraptionsToCrank"); }
@Override public int chooseSprocket(Card assignee, List<Integer> sprockets) { throw unsupported("chooseSprocket"); }
@Override public PlanarDice choosePDRollToIgnore(List<PlanarDice> rolls) { throw unsupported("choosePDRollToIgnore"); }
@Override public Integer chooseRollToIgnore(List<Integer> rolls) { throw unsupported("chooseRollToIgnore"); }
@Override public List<Integer> chooseDiceToReroll(List<Integer> rolls) { throw unsupported("chooseDiceToReroll"); }
@Override public Integer chooseRollToModify(List<Integer> rolls) { throw unsupported("chooseRollToModify"); }
@Override public RollDiceEffect.DieRollResult chooseRollToSwap(List<RollDiceEffect.DieRollResult> rolls) { throw unsupported("chooseRollToSwap"); }
@Override public String chooseRollSwapValue(List<String> swapChoices, Integer currentResult, int power, int toughness) { throw unsupported("chooseRollSwapValue"); }
@Override public Object vote(SpellAbility sa, String prompt, List<Object> options, ListMultimap<Object, Player> votes, Player forPlayer, boolean optional) { throw unsupported("vote"); }
@Override public boolean mulliganKeepHand(Player player, int cardsToReturn) { throw unsupported("mulliganKeepHand"); }
@Override public CardCollectionView tuckCardsViaMulligan(CardCollectionView hand, int cardsToReturn) { throw unsupported("tuckCardsViaMulligan"); }
@Override public List<SpellAbility> chooseSpellAbilityToPlay() { throw unsupported("chooseSpellAbilityToPlay"); }
@Override public boolean playChosenSpellAbility(SpellAbility sa) { throw unsupported("playChosenSpellAbility"); }
@Override public List<AbilitySub> chooseModeForAbility(SpellAbility sa, List<AbilitySub> possible, int min, int num, boolean allowRepeat) { throw unsupported("chooseModeForAbility"); }
@Override public int chooseNumberForCostReduction(final SpellAbility sa, final int min, final int max) { throw unsupported("chooseNumberForCostReduction"); }
@Override public int chooseNumberForKeywordCost(SpellAbility sa, Cost cost, KeywordInterface keyword, String prompt, int max) { throw unsupported("chooseNumberForKeywordCost"); }
@Override public int chooseNumber(SpellAbility sa, String title, int min, int max) { throw unsupported("chooseNumber"); }
@Override public int chooseNumber(SpellAbility sa, String title, List<Integer> values, Player relatedPlayer) { throw unsupported("chooseNumber"); }
@Override public boolean chooseBinary(SpellAbility sa, String question, BinaryChoiceType kindOfChoice, Boolean defaultChoice) { throw unsupported("chooseBinary"); }
@Override public boolean chooseFlipResult(SpellAbility sa, Player flipper, boolean call) { throw unsupported("chooseFlipResult"); }
@Override public byte chooseColor(String message, SpellAbility sa, ColorSet colors) { throw unsupported("chooseColor"); }
@Override public byte chooseColorAllowColorless(String message, Card c, ColorSet colors) { throw unsupported("chooseColorAllowColorless"); }
@Override public ColorSet chooseColors(String message, SpellAbility sa, int min, int max, ColorSet options) { throw unsupported("chooseColors"); }
@Override public ICardFace chooseSingleCardFace(SpellAbility sa, String message, Predicate<ICardFace> cpp, String name) { throw unsupported("chooseSingleCardFace"); }
@Override public ICardFace chooseSingleCardFace(SpellAbility sa, List<ICardFace> faces, String message) { throw unsupported("chooseSingleCardFace"); }
@Override public CardState chooseSingleCardState(SpellAbility sa, List<CardState> states, String message, Map<String, Object> params) { throw unsupported("chooseSingleCardState"); }
@Override public boolean chooseCardsPile(SpellAbility sa, CardCollectionView pile1, CardCollectionView pile2, String faceUp) { throw unsupported("chooseCardsPile"); }
@Override public CounterType chooseCounterType(List<CounterType> options, SpellAbility sa, String prompt, Map<String, Object> params) { throw unsupported("chooseCounterType"); }
@Override public String chooseKeywordForPump(List<String> options, SpellAbility sa, String prompt, Card tgtCard) { throw unsupported("chooseKeywordForPump"); }
@Override public boolean confirmPayment(CostPart costPart, String string, SpellAbility sa) { throw unsupported("confirmPayment"); }
@Override public ReplacementEffect chooseSingleReplacementEffect(List<ReplacementEffect> possibleReplacers) { throw unsupported("chooseSingleReplacementEffect"); }
@Override public StaticAbility chooseSingleStaticAbility(List<StaticAbility> possibleReplacers) { throw unsupported("chooseSingleStaticAbility"); }
@Override public String chooseProtectionType(SpellAbility sa, List<String> choices) { throw unsupported("chooseProtectionType"); }
@Override public void revealAnte(String message, Multimap<Player, PaperCard> removedAnteCards) { throw unsupported("revealAnte"); }
@Override public void revealAISkipCards(String message, Map<Player, Map<DeckSection, List<? extends PaperCard>>> deckCards) { throw unsupported("revealAISkipCards"); }
@Override public void revealUnsupported(Map<Player, List<PaperCard>> unsupported) { throw unsupported("revealUnsupported"); }
@Override public List<OptionalCostValue> chooseOptionalCosts(SpellAbility choosen, List<OptionalCostValue> optionalCostValues) { throw unsupported("chooseOptionalCosts"); }
@Override public List<CostPart> orderCosts(List<CostPart> costs) { throw unsupported("orderCosts"); }
@Override public boolean payCostToPreventEffect(Cost cost, SpellAbility sa, boolean alreadyPaid, FCollectionView<Player> allPayers) { throw unsupported("payCostToPreventEffect"); }
@Override public boolean payCostDuringRoll(Cost cost, SpellAbility sa) { throw unsupported("payCostDuringRoll"); }
@Override public boolean payCombatCost(Card card, Cost cost, SpellAbility sa, String prompt) { throw unsupported("payCombatCost"); }
@Override public boolean payManaCost(ManaCost toPay, CostPartMana costPartMana, SpellAbility sa, String prompt, ManaConversionMatrix matrix, boolean effect) { throw unsupported("payManaCost"); }
@Override public boolean applyManaToCost(ManaCostBeingPaid toPay, SpellAbility ability, String prompt, ManaConversionMatrix matrix, boolean effect) { throw unsupported("applyManaToCost"); }
@Override public CardCollectionView chooseCardsForCost(CardCollectionView optionList, SpellAbility sa, CostPartWithList cpl, int amount, boolean isOptional, String prompt) { throw unsupported("chooseCardsForCost"); }
@Override public CostDecisionMakerBase getCostDecisionMaker(Player player, SpellAbility ability, boolean effect, String prompt) { throw unsupported("getCostDecisionMaker"); }
@Override public String chooseCardName(SpellAbility sa, Predicate<ICardFace> cpp, String valid, String message) { throw unsupported("chooseCardName"); }
@Override public String chooseCardName(SpellAbility sa, List<ICardFace> faces, String message) { throw unsupported("chooseCardName"); }
@Override public Card chooseSingleCardForZoneChange(ZoneType destination, List<ZoneType> origin, SpellAbility sa, CardCollection fetchList, DelayedReveal delayedReveal, String selectPrompt, boolean isOptional, Player decider) { throw unsupported("chooseSingleCardForZoneChange"); }
@Override public List<Card> chooseCardsForZoneChange(ZoneType destination, List<ZoneType> origin, SpellAbility sa, CardCollection fetchList, int min, int max, DelayedReveal delayedReveal, String selectPrompt, Player decider) { throw unsupported("chooseCardsForZoneChange"); }
@Override public void autoPassCancel() { throw unsupported("autoPassCancel"); }
@Override public void awaitNextInput() { throw unsupported("awaitNextInput"); }
@Override public void cancelAwaitNextInput() { throw unsupported("cancelAwaitNextInput"); }
}
