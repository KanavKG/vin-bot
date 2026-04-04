from typing import Dict, List, Optional

from treys import Card, Deck, Evaluator


class EquityHelper:
    """Monte Carlo poker equity calculator."""

    def __init__(self, default_iterations: int = 10000):
        self.default_iterations = default_iterations
        self.evaluator = Evaluator()

    def parse_cards(self, card_string: str) -> List[int]:
        card_string = (card_string or "").replace(" ", "")
        cards: List[int] = []

        for i in range(0, len(card_string), 2):
            if i + 1 < len(card_string):
                cards.append(Card.new(card_string[i : i + 2]))

        return cards

    def calculate(
        self,
        hero_cards: str,
        villain_cards: str,
        board_cards: str = "",
        iterations: Optional[int] = None,
    ) -> Dict[str, float]:
        iterations = iterations if iterations is not None else self.default_iterations

        if iterations <= 0:
            raise ValueError("Iterations must be a positive integer")

        hero = self.parse_cards(hero_cards)
        villain = self.parse_cards(villain_cards)
        board = self.parse_cards(board_cards) if board_cards else []

        if len(hero) != 2 or len(villain) != 2:
            raise ValueError("Each hand must have exactly 2 cards")

        if len(board) > 5:
            raise ValueError("Board cannot have more than 5 cards")

        all_cards = hero + villain + board
        if len(all_cards) != len(set(all_cards)):
            raise ValueError("Duplicate cards detected")

        wins = ties = losses = 0

        for _ in range(iterations):
            deck = Deck()
            for card in all_cards:
                deck.cards.remove(card)

            sim_board = board.copy()
            cards_needed = 5 - len(board)
            sim_board.extend(deck.draw(cards_needed))

            hero_score = self.evaluator.evaluate(sim_board, hero)
            villain_score = self.evaluator.evaluate(sim_board, villain)

            if hero_score < villain_score:
                wins += 1
            elif hero_score == villain_score:
                ties += 1
            else:
                losses += 1

        return {
            "win": round((wins / iterations) * 100, 2),
            "tie": round((ties / iterations) * 100, 2),
            "lose": round((losses / iterations) * 100, 2),
            "simulations": iterations,
        }
