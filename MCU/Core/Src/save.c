#include "save.h"
#include "stm32f0xx_hal.h"
#include <string.h>

extern uint8_t board[BOARD_ROWS][BOARD_COLS];
extern uint32_t score;

char current_player_name[16] = "Player1";

void Save_Game(uint8_t slot) {
    if (slot >= MAX_SAVE_SLOTS) return; // Захист від помилок

    // Створюємо масив для всіх 3 слотів у RAM
    GameSaveData_t all_slots[MAX_SAVE_SLOTS];
    GameSaveData_t *flash_ptr = (GameSaveData_t *)FLASH_SAVE_ADDR;

    // 1. Копіюємо всі існуючі збереження з Flash в RAM
    for(int i = 0; i < MAX_SAVE_SLOTS; i++) {
        all_slots[i] = flash_ptr[i];
    }

    // 2. Оновлюємо ТІЛЬКИ вибраний слот
    all_slots[slot].magic = SAVE_MAGIC_NUMBER;
    all_slots[slot].score = score;
    memset(all_slots[slot].playerName, 0, 16);
    strncpy(all_slots[slot].playerName, current_player_name, 15);
    memcpy(all_slots[slot].board, board, sizeof(board));

    // 3. Відкриваємо Flash для запису
    HAL_FLASH_Unlock();

    // Стираємо всю сторінку
    FLASH_EraseInitTypeDef EraseInitStruct;
    uint32_t PageError;
    EraseInitStruct.TypeErase = FLASH_TYPEERASE_PAGES;
    EraseInitStruct.PageAddress = FLASH_SAVE_ADDR;
    EraseInitStruct.NbPages = 1;
    HAL_FLASHEx_Erase(&EraseInitStruct, &PageError);

    // Записуємо всі 3 слоти назад у Flash
    uint32_t *data_ptr = (uint32_t *)all_slots;
    uint32_t words_to_write = sizeof(all_slots) / 4;

    for (uint32_t i = 0; i < words_to_write; i++) {
        HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, FLASH_SAVE_ADDR + (i * 4), data_ptr[i]);
    }

    HAL_FLASH_Lock();
}

int Load_Game(uint8_t slot) {
    if (slot >= MAX_SAVE_SLOTS) return 0;

    // Читаємо як масив структур
    GameSaveData_t *flashData = (GameSaveData_t *)FLASH_SAVE_ADDR;

    // Перевіряємо магічне число саме в потрібному слоті
    if (flashData[slot].magic == SAVE_MAGIC_NUMBER) {
        score = flashData[slot].score;
        memset(current_player_name, 0, 16);
        strncpy(current_player_name, flashData[slot].playerName, 15);
        memcpy(board, flashData[slot].board, sizeof(board));
        return 1; // Успіх
    }

    return 0; // Цей слот порожній
}
