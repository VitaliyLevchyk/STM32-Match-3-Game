/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body (Protocol Handler with Diff Update)
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <string.h>
#include "game.h"
#include "save.h" // <--- ДОДАНО: ОБОВ'ЯЗКОВЕ ПІДКЛЮЧЕННЯ ФАЙЛУ ЗБЕРЕЖЕННЯ
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
typedef struct {
	uint8_t cmd;
	uint8_t addr_h;
	uint8_t addr_l;
	uint8_t data_h;
	uint8_t data_l;
	uint8_t crc;
} Packet_t;
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define PACKET_SIZE 6
#define TIMEOUT_MS  10

// Коди команд для відповіді
#define CMD_UPDATE_CELL 0x16
/* USER CODE END PD */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN PV */
uint8_t rx_byte;
uint8_t rx_buffer[PACKET_SIZE];
uint8_t rx_idx = 0;
volatile uint8_t packet_received_flag = 0;
uint32_t last_byte_tick = 0;
Packet_t current_packet;
extern char current_player_name[16]; // Змінна з save.c

// Буфер для збереження старого стану поля (Snapshot)
uint8_t board_snapshot[BOARD_ROWS][BOARD_COLS];

// === НАЛАШТУВАННЯ АНІМАЦІЇ ===
// Затримка між кроками падіння кубиків (у мілісекундах). Змінюй це значення!
uint32_t anim_speed_ms = 300;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);

/* USER CODE BEGIN 0 */
// Функція розрахунку CRC
uint8_t CRC8_Calc(uint8_t *data, uint8_t len)
{
	uint8_t crc = 0x00;
	uint8_t i, j;
	for (i = 0; i < len; i++) {
		crc ^= data[i];
		for (j = 0; j < 8; j++) {
			if (crc & 0x80) {
				crc = (crc << 1) ^ 0x07;
			} else {
				crc <<= 1;
			}
		}
	}
	return crc;
}

// Універсальна функція відправки пакету
void Send_Packet(uint8_t cmd, uint8_t r, uint8_t c, uint8_t data, uint8_t status)
{
    uint8_t tx_buf[PACKET_SIZE];
    tx_buf[0] = cmd;
    tx_buf[1] = r;
    tx_buf[2] = c;
    tx_buf[3] = data;
    tx_buf[4] = status;
    tx_buf[5] = CRC8_Calc(tx_buf, 5);

    HAL_UART_Transmit(&huart1, tx_buf, PACKET_SIZE, 100);
}

// Відправка різниці (оновлення екрану)
void Send_Board_Diff(void)
{
    for (uint8_t r = 0; r < BOARD_ROWS; r++) {
        for (uint8_t c = 0; c < BOARD_COLS; c++) {
            if (board[r][c] != board_snapshot[r][c]) {
                Send_Packet(CMD_UPDATE_CELL, r, c, board[r][c], 0xAA);
                HAL_Delay(2);
            }
        }
    }
}

// Викликається з game.c для відмальовки кожного кроку анімації
void UI_Update_Step(void)
{
    Send_Board_Diff(); // Відправляємо зміни
    memcpy(board_snapshot, board, sizeof(board_snapshot)); // Оновлюємо знімок для наступного кадру

    if (anim_speed_ms > 0) {
        HAL_Delay(anim_speed_ms); // Чекаємо, щоб око встигло побачити кадр
    }
}

void Send_Full_Board(void)
{
    for (uint8_t r = 0; r < BOARD_ROWS; r++) {
        for (uint8_t c = 0; c < BOARD_COLS; c++) {
            Send_Packet(CMD_UPDATE_CELL, r, c, board[r][c], 0xAA);
            HAL_Delay(2);
        }
    }
}
/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{
  HAL_Init();
  SystemClock_Config();
  MX_GPIO_Init();
  MX_USART1_UART_Init();

  /* USER CODE BEGIN 2 */
  __HAL_UART_FLUSH_DRREGISTER(&huart1);
  HAL_UART_Receive_IT(&huart1, &rx_byte, 1);

  Game_Init();
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
      if (packet_received_flag == 1)
      {
          current_packet.cmd    = rx_buffer[0];
          current_packet.addr_h = rx_buffer[1];
          current_packet.addr_l = rx_buffer[2];
          current_packet.data_h = rx_buffer[3];
          current_packet.data_l = rx_buffer[4];
          current_packet.crc    = rx_buffer[5];

          uint8_t calc_crc = CRC8_Calc(rx_buffer, 5);

          if (calc_crc == current_packet.crc)
          {
              switch (current_packet.cmd)
              {
                  case 0x10: // NEW GAME
                      Game_Init();
                      Send_Packet(0x10, 0, 0, 0, 0xAA);
                      Send_Full_Board();
                      break;

                  case 0x11: // SWAP
                  {
                      memcpy(board_snapshot, board, sizeof(board_snapshot));

                      // Game_Swap тепер тільки спалює кубики, але НЕ запускає падіння миттєво
                      uint8_t success = Game_Swap(current_packet.addr_h, current_packet.addr_l,
                                                  current_packet.data_h, current_packet.data_l);

                      if (success) {
                          // Відразу підтверджуємо, що хід валідний, щоб UI розблокувався
                          Send_Packet(0x11, 0, 0, 0, 0xAA);

                          // 1. Показуємо зникнення згорілих кубиків (вони стали 0)
                          UI_Update_Step();

                          // 2. Запускаємо покрокову анімацію падіння
                          Game_RunGravityLoop();

                          // 3. ПЕРЕВІРКА НА ГЛУХИЙ КУТ після того, як все впало
                          if (Game_HasPossibleMoves() == 0) {
                              Send_Packet(0x11, 0, 0, 0, 0xDD);
                          }
                      } else {
                          Send_Packet(0x11, 0, 0, 0, 0xEE); // Помилка
                      }
                  }
                  break;

                  case 0x14: // GET CELL
                  {
                      uint8_t r = current_packet.addr_h;
                      uint8_t c = current_packet.addr_l;

                      if (r < BOARD_ROWS && c < BOARD_COLS) {
                          Send_Packet(0x14, r, c, board[r][c], 0xAA);
                      } else {
                          Send_Packet(0x14, r, c, 0, 0xEE);
                      }
                  }
                  break;

                  case 0x15: // GET SCORE
                  {
                      uint8_t tx_score[PACKET_SIZE];
                      tx_score[0] = 0x15;
                      tx_score[1] = (uint8_t)((score >> 24) & 0xFF);
                      tx_score[2] = (uint8_t)((score >> 16) & 0xFF);
                      tx_score[3] = (uint8_t)((score >> 8)  & 0xFF);
                      tx_score[4] = (uint8_t)(score & 0xFF);
                      tx_score[5] = CRC8_Calc(tx_score, 5);

                      HAL_UART_Transmit(&huart1, tx_score, PACKET_SIZE, 100);
                  }
                  break;

                  case 0x20: // ПРИЙОМ ІМЕНІ ВІД PYTHON ПРИ СТАРТІ (по 3 символи)
                  {
                      uint8_t chunk = current_packet.addr_h;
                      if (chunk < 6) {
                          int base = chunk * 3;
                          if (base < 16) current_player_name[base] = current_packet.addr_l;
                          if (base + 1 < 16) current_player_name[base + 1] = current_packet.data_h;
                          if (base + 2 < 16) current_player_name[base + 2] = current_packet.data_l;
                      }
                      if (chunk == 5) current_player_name[15] = '\0'; // Гарантуємо кінець рядка
                      Send_Packet(0x20, chunk, 0, 0, 0xAA);
                  }
                  break;

                  case 0x30: // ЗБЕРЕГТИ ГРУ (Save)
                  {
                      uint8_t slot = current_packet.addr_h; // Python пришле 0, 1 або 2
                      Save_Game(slot);
                      Send_Packet(0x30, slot, 0, 0, 0xAA);
                  }
                  break;

                  case 0x31: // ВІДНОВИТИ ГРУ (Restore / Load)
                  {
                      uint8_t slot = current_packet.addr_h; // Python пришле 0, 1 або 2
                      if (Load_Game(slot) == 1) {
                          Send_Packet(0x31, slot, 0, 0, 0xAA);
                          HAL_Delay(10);

                          for (uint8_t i = 0; i < 6; i++) {
                              Send_Packet(0x32, i,
                                          current_player_name[i*3],
                                          current_player_name[i*3+1],
                                          current_player_name[i*3+2]);
                              HAL_Delay(5);
                          }

                          uint8_t tx_sc[PACKET_SIZE] = {0x15, (uint8_t)((score>>24)&0xFF), (uint8_t)((score>>16)&0xFF), (uint8_t)((score>>8)&0xFF), (uint8_t)(score&0xFF), 0};
                          tx_sc[5] = CRC8_Calc(tx_sc, 5);
                          HAL_UART_Transmit(&huart1, tx_sc, PACKET_SIZE, 100);
                          HAL_Delay(10);

                          Send_Full_Board();
                      } else {
                          Send_Packet(0x31, slot, 0, 0, 0xEE); // Помилка: слот порожній
                      }
                  }
                  break;

                  default: // Невідома команда
                      Send_Packet(current_packet.cmd, 0, 0, 0, 0xFF);
                      break;
              }
          }
          else
          {
              Send_Packet(0xEE, calc_crc, current_packet.crc, 0xEE, 0xEE);
          }

          packet_received_flag = 0;
          rx_idx = 0;
      }
  }
  /* USER CODE END 3 */
}

void SystemClock_Config(void) {
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
  RCC_PeriphCLKInitTypeDef PeriphClkInit = {0};
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL12;
  RCC_OscInitStruct.PLL.PREDIV = RCC_PREDIV_DIV1;
  HAL_RCC_OscConfig(&RCC_OscInitStruct);
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK|RCC_CLOCKTYPE_PCLK1;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_1);
  PeriphClkInit.PeriphClockSelection = RCC_PERIPHCLK_USART1;
  PeriphClkInit.Usart1ClockSelection = RCC_USART1CLKSOURCE_PCLK1;
  HAL_RCCEx_PeriphCLKConfig(&PeriphClkInit);
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart) {
  if (huart->Instance == USART1) {
	uint32_t current_tick = HAL_GetTick();
	if (rx_idx > 0 && (current_tick - last_byte_tick > TIMEOUT_MS)) rx_idx = 0;
	last_byte_tick = current_tick;

	if (packet_received_flag == 0) {
		rx_buffer[rx_idx++] = rx_byte;
		if (rx_idx >= PACKET_SIZE) {
			packet_received_flag = 1;
			rx_idx = 0;
		}
	}
	HAL_UART_Receive_IT(&huart1, &rx_byte, 1);
  }
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart) {
  if (huart->Instance == USART1) {
	__HAL_UART_CLEAR_OREFLAG(huart);
	rx_idx = 0;
	packet_received_flag = 0;
	HAL_UART_Receive_IT(&huart1, &rx_byte, 1);
  }
}

void Error_Handler(void) {
  __disable_irq();
  while (1) {}
}
