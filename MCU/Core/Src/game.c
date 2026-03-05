#include "game.h"
#include <stdlib.h>
#include <string.h>

// Глобальні змінні
uint8_t board[BOARD_ROWS][BOARD_COLS];
uint32_t score = 0;

// Функція оновлення екрану з main.c
extern void UI_Update_Step(void);

/* --- ПРОТОТИПИ --- */
static uint8_t GetValidRandomColor(int r, int c);
static int Game_GravityStep(void); // Оновлений крок гравітації
static int Game_CheckAndRemoveMatches(void);
static uint32_t GetScoreForCount(uint8_t count);
static int Game_IsMatchPresent(void);

/* --- ПУБЛІЧНІ ФУНКЦІЇ --- */

void Game_Init(void) {
    score = 0;
    // Заповнюємо поле без анімацій
    for (int r = 0; r < BOARD_ROWS; r++) {
        for (int c = 0; c < BOARD_COLS; c++) {
            board[r][c] = GetValidRandomColor(r, c);
        }
    }
}

uint8_t Game_Swap(uint8_t r1, uint8_t c1, uint8_t r2, uint8_t c2) {
    if (r1 >= BOARD_ROWS || c1 >= BOARD_COLS || r2 >= BOARD_ROWS || c2 >= BOARD_COLS) return 0;

    int diff_r = abs((int)r1 - (int)r2);
    int diff_c = abs((int)c1 - (int)c2);
    if ((diff_r + diff_c) != 1) return 0;

    // Тимчасовий обмін
    uint8_t temp = board[r1][c1];
    board[r1][c1] = board[r2][c2];
    board[r2][c2] = temp;

    if (Game_CheckAndRemoveMatches()) {
        // Збіг знайдено і видалено (замінено на 0).
        // Повертаємо 1. Сама анімація і гравітація запускаються з main.c
        return 1;
    } else {
        // Скасування обміну
        board[r2][c2] = board[r1][c1];
        board[r1][c1] = temp;
        return 0;
    }
}

uint8_t Game_HasPossibleMoves(void) {
    for (int r = 0; r < BOARD_ROWS; r++) {
        for (int c = 0; c < BOARD_COLS; c++) {
            if (c < BOARD_COLS - 1) {
                uint8_t temp = board[r][c];
                board[r][c] = board[r][c+1];
                board[r][c+1] = temp;
                int has_match = Game_IsMatchPresent();
                board[r][c+1] = board[r][c];
                board[r][c] = temp;
                if (has_match) return 1;
            }
            if (r < BOARD_ROWS - 1) {
                uint8_t temp = board[r][c];
                board[r][c] = board[r+1][c];
                board[r+1][c] = temp;
                int has_match = Game_IsMatchPresent();
                board[r+1][c] = board[r][c];
                board[r][c] = temp;
                if (has_match) return 1;
            }
        }
    }
    return 0;
}

// Головний цикл гравітації (Тепер ПУБЛІЧНИЙ, викликається з main.c)
void Game_RunGravityLoop(void) {
    int matches_found;
    do {
        // 1. Покрокове падіння вже існуючих кубиків
        int moved;
        do {
            moved = Game_GravityStep();
            if (moved) UI_Update_Step();
        } while (moved);

        // 2. Потокова генерація і падіння нових кубиків згори
        int needs_fill;
        do {
            needs_fill = 0;

            // Заповнюємо верхній ряд, якщо там порожньо
            for (int c = 0; c < BOARD_COLS; c++) {
                if (board[0][c] == 0) {
                    board[0][c] = (rand() % 6) + 1;
                    needs_fill = 1;
                }
            }

            if (needs_fill) {
                UI_Update_Step(); // З'явилися нові
            }

            // Робимо один крок падіння для всіх, щоб звільнити верхній ряд
            if (Game_GravityStep()) {
                UI_Update_Step(); // Впали на 1 крок
                needs_fill = 1; // Продовжуємо, бо ще є рух
            }
        } while (needs_fill);

        // 3. Після того, як все впало, перевіряємо, чи не утворились нові "3-в-ряд" (комбо)
        matches_found = Game_CheckAndRemoveMatches();
        if (matches_found) {
            UI_Update_Step(); // Показуємо згорання нових кубиків
        }
    } while (matches_found);
}

/* --- ПРИВАТНІ ФУНКЦІЇ --- */

// Виконує РІВНО ОДИН крок падіння (всі кубики, під якими порожньо, падають на 1 клітинку)
static int Game_GravityStep(void) {
    int moved = 0;
    for (int c = 0; c < BOARD_COLS; c++) {
        // Йдемо знизу вгору, щоб кубики не пролітали все поле за один прохід
        for (int r = BOARD_ROWS - 2; r >= 0; r--) {
            if (board[r][c] != 0 && board[r+1][c] == 0) {
                board[r+1][c] = board[r][c];
                board[r][c] = 0;
                moved = 1;
            }
        }
    }
    return moved;
}

static int Game_CheckAndRemoveMatches(void) {
    uint8_t marked[BOARD_ROWS][BOARD_COLS] = {0};
    int found_match = 0;

    for (int r = 0; r < BOARD_ROWS; r++) {
        for (int c = 0; c <= BOARD_COLS - 3; c++) {
            uint8_t color = board[r][c];
            if (color == 0) continue;
            if (board[r][c+1] == color && board[r][c+2] == color) {
                found_match = 1;
                marked[r][c] = marked[r][c+1] = marked[r][c+2] = 1;
            }
        }
    }

    for (int c = 0; c < BOARD_COLS; c++) {
        for (int r = 0; r <= BOARD_ROWS - 3; r++) {
            uint8_t color = board[r][c];
            if (color == 0) continue;
            if (board[r+1][c] == color && board[r+2][c] == color) {
                found_match = 1;
                marked[r][c] = marked[r+1][c] = marked[r+2][c] = 1;
            }
        }
    }

    if (found_match) {
        uint8_t count = 0;
        for (int r = 0; r < BOARD_ROWS; r++) {
            for (int c = 0; c < BOARD_COLS; c++) {
                if (marked[r][c]) {
                    board[r][c] = 0;
                    count++;
                }
            }
        }
        score += GetScoreForCount(count);
    }
    return found_match;
}

static uint32_t GetScoreForCount(uint8_t count) {
    if (count == 3) return 30;
    if (count == 4) return 60;
    if (count >= 5) return 100;
    return count * 10;
}

static uint8_t GetValidRandomColor(int r, int c) {
    uint8_t color;
    int is_valid;
    do {
        color = (rand() % 6) + 1;
        is_valid = 1;
        if (c >= 2 && board[r][c-1] == color && board[r][c-2] == color) is_valid = 0;
        if (r >= 2 && board[r-1][c] == color && board[r-2][c] == color) is_valid = 0;
    } while (!is_valid);
    return color;
}

static int Game_IsMatchPresent(void) {
    for (int r = 0; r < BOARD_ROWS; r++) {
        for (int c = 0; c <= BOARD_COLS - 3; c++) {
            uint8_t color = board[r][c];
            if (color == 0) continue;
            if (board[r][c+1] == color && board[r][c+2] == color) return 1;
        }
    }
    for (int c = 0; c < BOARD_COLS; c++) {
        for (int r = 0; r <= BOARD_ROWS - 3; r++) {
            uint8_t color = board[r][c];
            if (color == 0) continue;
            if (board[r+1][c] == color && board[r+2][c] == color) return 1;
        }
    }
    return 0;
}
