"""Versioned fictional-hotel dataset contract tests."""

from hotel_bot.seed import load_seed_dataset


def test_seed_dataset_is_complete_bilingual_and_coherent() -> None:
    dataset = load_seed_dataset()

    assert dataset.dataset_version == "1.0.0"
    assert dataset.hotel.code == "nour-al-sham-grand"
    assert set(dataset.hotel.names) == {"ar", "en"}
    assert len(dataset.room_types) == 5
    assert len(dataset.rooms) == 22
    assert len(dataset.guests) == 6
    assert len(dataset.bookings) == 8
    assert len(dataset.service_requests) == 3
    assert all(set(room_type.names) == {"ar", "en"} for room_type in dataset.room_types)
