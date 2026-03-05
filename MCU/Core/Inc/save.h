#ifndef INC_SAVE_H_
#define INC_SAVE_H_

#include <stdint.h>
#include "game.h"

#define FLASH_SAVE_ADDR     0x0800FC00
#define SAVE_MAGIC_NUMBER   0xABBA1234
#define MAX_SAVE_SLOTS      3 // <--- ДОДАНО: 3 слоти збереження

typedef struct {
    uint32_t magic;
    uint32_t score;
    char     playerName[16];
    uint8_t  board[BOARD_ROWS][BOARD_COLS];
} GameSaveData_t;

extern char current_player_name[16];

// Тепер функції приймають номер слота (0, 1 або 2)
void Save_Game(uint8_t slot);
int  Load_Game(uint8_t slot);

#endif /* INC_SAVE_H_ */
