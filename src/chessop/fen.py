"""FEN helpers shared across the package.

A position's *identity* (for the graph and the caches) is the normalized FEN:
piece placement, side to move, castling rights and en-passant square. The
halfmove clock and fullmove number are dropped — they don't change which
position you're looking at, and keeping them would stop transpositions from
collapsing onto one node.
"""
import chess


def normalize(fen: str) -> str:
    """The 4-field position-identity key."""
    return " ".join(fen.split()[:4])


def side_to_move(fen: str) -> str:
    """'w' or 'b'."""
    return fen.split()[1]


def to_board(fen: str) -> chess.Board:
    """A python-chess Board, tolerating a normalized (4-field) FEN.

    Move counters don't affect legality or the resulting position, so we append
    placeholders when they're missing.
    """
    parts = fen.split()
    if len(parts) == 4:
        parts += ["0", "1"]
    return chess.Board(" ".join(parts))
