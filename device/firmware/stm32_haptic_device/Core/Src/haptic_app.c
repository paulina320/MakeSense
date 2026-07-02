#include "haptic_app.h"

#include "haptic_protocol.h"
#include "haptic_usb.h"
#include "imu_sensors.h"
#include "max11300.h"
#include "main.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HAPTIC_VERSION "stm32_haptic_device_0.4"
#define CHANNEL_COUNT 20U
#define RENDER_CAPACITY 8192U
#define LINE_BUFFER_SIZE 128U
#define ACQ_FLUSH_INTERVAL_US 5000UL
#define MAX_SCHEDULER_CATCHUP 8U
#define MAX_RENDER_CATCHUP 2U
#define MAX_PENDING_TICKS 65535U
#define RX_BYTES_PER_TICK_IDLE 256U
#define MIN_DMA_BURST_WORDS 4U
#define DEFAULT_IMU_STREAM_RATE_HZ 100UL
#define MAX_IMU_STREAM_RATE_HZ 3200UL
#define IMU_SAMPLE_PAYLOAD_SIZE 32U
#define IMU_MAX_BATCH_SAMPLES (HAPTIC_MAX_BINARY_PAYLOAD / IMU_SAMPLE_PAYLOAD_SIZE)
#define IMU_FLUSH_INTERVAL_US 10000UL
#define DAC_RENDER_BIAS_MV 2500L
#define DAC_RENDER_LIMIT_DELTA_MV 300L
#define DAC_0_10_FULL_SCALE_MV 10000L
#define DAC_12BIT_COUNTS 4096L
#define DAC_RENDER_BIAS_CODE ((uint16_t)((DAC_RENDER_BIAS_MV * DAC_12BIT_COUNTS + (DAC_0_10_FULL_SCALE_MV / 2L)) / DAC_0_10_FULL_SCALE_MV))
#define DAC_RENDER_LIMIT_DELTA_CODE ((int32_t)((DAC_RENDER_LIMIT_DELTA_MV * DAC_12BIT_COUNTS + (DAC_0_10_FULL_SCALE_MV / 2L)) / DAC_0_10_FULL_SCALE_MV))
#define RENDER_MAX_CONSECUTIVE_UNDERRUNS 50000U
#define DAC_SINE_TEST_SAMPLE_RATE_HZ 10000UL
#define DAC_SINE_TEST_DEFAULT_DURATION_MS 2000UL
#define DAC_SINE_TEST_DEFAULT_FREQ_HZ 200UL
#define DAC_SINE_TEST_TABLE_SIZE 50U

extern SPI_HandleTypeDef hspi1;
extern TIM_HandleTypeDef htim2;

typedef enum {
  ROLE_HIGH_Z = 0,
  ROLE_INPUT,
  ROLE_OUTPUT,
  ROLE_DIFFERENTIAL,
} ChannelRole;

typedef struct {
  ChannelRole role;
  int8_t partner;
  uint16_t adc_range;
  uint16_t dac_range;
  uint8_t averaging;
  bool stream;
  uint16_t last_value;
} ChannelState;

typedef enum {
  PARSE_TEXT = 0,
  PARSE_SYNC1,
  PARSE_HEADER,
  PARSE_PAYLOAD,
  PARSE_CRC,
  PARSE_DISCARD,
} ParseState;

static Max11300 pixi;
static bool pixi_ok = false;
static bool acquiring = false;
static bool rendering = false;

static uint32_t sample_rate_hz = 10000UL;
static uint32_t sample_interval_us = 1000000UL / 44100UL;
static uint32_t last_acquisition_flush_us = 0;

static bool imu_stream_enabled = false;
static uint32_t imu_stream_rate_hz = DEFAULT_IMU_STREAM_RATE_HZ;
static uint32_t imu_stream_interval_us = 1000000UL / DEFAULT_IMU_STREAM_RATE_HZ;
static uint8_t imu_sensor_mask = IMU_SELECT_ALL;
static uint32_t next_imu_stream_us = 0;
static uint32_t last_imu_flush_us = 0;

static uint32_t max_imu_rate_for_mask(uint8_t mask) {
  uint8_t count = 0U;
  for (uint8_t bit = 0U; bit < 4U; bit++) {
    if ((mask & (uint8_t)(1U << bit)) != 0U) {
      count++;
    }
  }
  if (count >= 4U) {
    return 800UL;
  }
  if (count == 3U) {
    return 1000UL;
  }
  if (count == 2U) {
    return 1600UL;
  }
  return MAX_IMU_STREAM_RATE_HZ;
}

static uint32_t dropped_frames = 0;
static uint32_t underruns = 0;
static uint32_t render_startup_underruns = 0;
static uint32_t render_overruns = 0;
static uint32_t render_overvolts = 0;
static uint32_t render_samples = 0;
static uint32_t render_bias_samples = 0;
static uint32_t render_underrun_bias_samples = 0;
static uint32_t render_late_ticks = 0;
static uint32_t render_spi_failures = 0;
static uint32_t render_tick_max_us = 0;
static uint16_t render_due_max = 0;
static uint16_t rx_queue_max = 0;
static uint16_t consecutive_render_underruns = 0;
static bool render_data_received = false;
static uint16_t tx_sequence = 0;
static volatile uint16_t acquisition_due = 0;
static volatile uint16_t render_due = 0;

static ChannelState channels[CHANNEL_COUNT];
static uint8_t stream_pins[CHANNEL_COUNT];
static uint8_t stream_pin_count = 0;
static uint8_t output_pins[CHANNEL_COUNT];
static uint8_t output_pin_count = 0;
static uint8_t stream_span_start = 0;
static uint8_t stream_span_count = 0;
static bool stream_pins_are_adjacent = false;
static uint8_t output_span_start = 0;
static uint8_t output_span_count = 0;
static bool output_pins_are_adjacent = false;

static uint16_t render_ring[RENDER_CAPACITY];
static uint16_t render_head = 0;
static uint16_t render_tail = 0;

static const int16_t dac_sine_table[DAC_SINE_TEST_TABLE_SIZE] = {
  0, 385, 764, 1131, 1480, 1806, 2103, 2368, 2595, 2781,
  2923, 3020, 3070, 3070, 3020, 2923, 2781, 2595, 2368, 2103,
  1806, 1480, 1131, 764, 385, 0, -385, -764, -1131, -1480,
  -1806, -2103, -2368, -2595, -2781, -2923, -3020, -3070, -3070, -3020,
  -2923, -2781, -2595, -2368, -2103, -1806, -1480, -1131, -764, -385,
};

static char line_buffer[LINE_BUFFER_SIZE];
static uint8_t line_length = 0;
static uint8_t pending_loopback[HAPTIC_MAX_BINARY_PAYLOAD];
static uint16_t pending_loopback_length = 0;
static bool loopback_pending = false;
static int16_t acquisition_payload[HAPTIC_MAX_BINARY_PAYLOAD / sizeof(int16_t)];
static uint8_t acquisition_payload_samples = 0;
static uint8_t imu_payload[HAPTIC_MAX_BINARY_PAYLOAD];
static uint8_t imu_payload_samples = 0;
static uint8_t tx_frame_buffer[HAPTIC_FRAME_HEADER_SIZE + HAPTIC_MAX_BINARY_PAYLOAD + HAPTIC_FRAME_CRC_SIZE];
static uint16_t acq_dma_raw[CHANNEL_COUNT];
static uint8_t acq_dma_start_pin = 0;
static uint8_t acq_dma_count = 0;
static bool acq_dma_adjacent = false;
static volatile bool acq_dma_inflight = false;
static volatile bool acq_dma_ready = false;
static volatile bool acq_dma_ok = false;
static uint16_t render_dma_values[CHANNEL_COUNT];
static volatile bool render_dma_inflight = false;
static volatile bool render_dma_done = false;
static volatile bool render_dma_ok = false;

static ParseState parse_state = PARSE_TEXT;
static uint8_t frame_header[HAPTIC_FRAME_HEADER_SIZE];
static uint8_t header_index = 0;
static uint8_t frame_payload[HAPTIC_MAX_BINARY_PAYLOAD];
static uint16_t frame_length = 0;
static uint16_t frame_index = 0;
static uint8_t frame_type = 0;
static uint16_t received_crc = 0;
static uint16_t discard_remaining = 0;
static uint32_t micros_last_cycles = 0;
static uint32_t micros_accumulated = 0;
static uint32_t micros_cycle_remainder = 0;
static uint32_t micros_cycles_per_us = 1;

static void flush_acquisition_frame(void);

static uint32_t micros_now(void) {
  uint32_t cycles = DWT->CYCCNT;
  uint32_t elapsed_cycles = cycles - micros_last_cycles;
  micros_last_cycles = cycles;

  /*
   * CYCCNT wraps every ~44.7 s at 96 MHz. Unsigned delta accumulation keeps
   * this clock monotonic across that wrap. The returned microsecond counter
   * then has the intended uint32_t wrap interval of ~71.6 minutes.
   */
  uint32_t total_cycles = micros_cycle_remainder + elapsed_cycles;
  micros_accumulated += total_cycles / micros_cycles_per_us;
  micros_cycle_remainder = total_cycles % micros_cycles_per_us;
  return micros_accumulated;
}

static void micros_init(void) {
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
  micros_cycles_per_us = HAL_RCC_GetHCLKFreq() / 1000000UL;
  if (micros_cycles_per_us == 0U) {
    micros_cycles_per_us = 1U;
  }
  micros_last_cycles = DWT->CYCCNT;
  micros_accumulated = 0U;
  micros_cycle_remainder = 0U;
}

static uint32_t tim2_clock_hz(void) {
  uint32_t pclk1 = HAL_RCC_GetPCLK1Freq();
  if ((RCC->CFGR & RCC_CFGR_PPRE1) != RCC_HCLK_DIV1) {
    pclk1 *= 2U;
  }
  return pclk1;
}

static void sample_timer_stop(void) {
  HAL_TIM_Base_Stop_IT(&htim2);
  __HAL_TIM_SET_COUNTER(&htim2, 0U);
  acquisition_due = 0;
  render_due = 0;
}

static void sample_timer_configure(void) {
  uint32_t timer_clock = tim2_clock_hz();
  uint32_t prescaler = (timer_clock / 1000000UL);
  if (prescaler == 0UL) {
    prescaler = 1UL;
  }
  uint32_t period = sample_interval_us > 0UL ? sample_interval_us : 1UL;

  HAL_TIM_Base_Stop_IT(&htim2);
  htim2.Init.Prescaler = prescaler - 1UL;
  htim2.Init.Period = period - 1UL;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  HAL_TIM_Base_Init(&htim2);
  __HAL_TIM_SET_COUNTER(&htim2, 0U);
  acquisition_due = 0;
  render_due = 0;
}

static void sample_timer_update_state(void) {
  if (acquiring || rendering) {
    __HAL_TIM_SET_COUNTER(&htim2, 0U);
    HAL_TIM_Base_Start_IT(&htim2);
  } else {
    sample_timer_stop();
  }
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim) {
  if (htim->Instance != TIM2) {
    return;
  }
  if (acquiring && acquisition_due < MAX_PENDING_TICKS) {
    acquisition_due++;
  }
  if (rendering && render_due < MAX_PENDING_TICKS) {
    render_due++;
  }
}

static uint16_t render_fill(void) {
  if (render_head >= render_tail) {
    return (uint16_t)(render_head - render_tail);
  }
  return (uint16_t)(RENDER_CAPACITY - render_tail + render_head);
}

static bool push_render(uint16_t value) {
  uint16_t next = (uint16_t)((render_head + 1U) % RENDER_CAPACITY);
  if (next == render_tail) {
    dropped_frames++;
    render_overruns++;
    return false;
  }
  render_ring[render_head] = value;
  render_head = next;
  render_data_received = true;
  return true;
}

static bool pop_render(uint16_t *value) {
  if (render_head == render_tail) {
    return false;
  }
  *value = render_ring[render_tail];
  render_tail = (uint16_t)((render_tail + 1U) % RENDER_CAPACITY);
  return true;
}

static void clear_render_ring(void) {
  render_head = 0;
  render_tail = 0;
}

static void stop_rendering_idle(bool write_bias) {
  rendering = false;
  render_due = 0;
  consecutive_render_underruns = 0;
  clear_render_ring();
  sample_timer_update_state();
  if (write_bias && pixi_ok) {
    for (uint8_t i = 0; i < output_pin_count; i++) {
      Max11300_WriteAnalogPin(&pixi, output_pins[i], DAC_RENDER_BIAS_CODE);
    }
  }
}

static uint16_t dac_code_from_0_10_millivolts(long millivolts) {
  int32_t code = (int32_t)((millivolts * DAC_12BIT_COUNTS + (DAC_0_10_FULL_SCALE_MV / 2L)) / DAC_0_10_FULL_SCALE_MV);
  if (code < 0L) {
    return 0U;
  }
  if (code > 4095L) {
    return 4095U;
  }
  return (uint16_t)code;
}

static uint16_t limited_render_dac_code(int16_t signed_sample) {
  /*
   * Render output is unipolar 0 V to 10 V, AC-coupled by the amplifier input.
   * The resting point is 2.5 V so AVDDIO=5 V still has headroom. Full-scale
   * host samples are intentionally scaled to +/-300 mV at the DAC input; with
   * 20 dB amplifier gain that is approximately +/-3 V after the amplifier.
   */
  int32_t delta = ((int32_t)signed_sample * DAC_RENDER_LIMIT_DELTA_CODE) / 32767L;

  int32_t code = (int32_t)DAC_RENDER_BIAS_CODE + delta;
  if (code < 0L) {
    return 0U;
  }
  if (code > 4095L) {
    return 4095U;
  }
  return (uint16_t)code;
}

static void send_frame(uint8_t type, const uint8_t *payload, uint16_t length) {
  if (length > HAPTIC_MAX_BINARY_PAYLOAD) {
    length = HAPTIC_MAX_BINARY_PAYLOAD;
  }
  uint16_t crc = HapticProtocol_FrameCrc(type, length, tx_sequence, payload);
  HapticProtocol_BuildHeader(tx_frame_buffer, type, length, tx_sequence);
  if (payload != NULL && length > 0U) {
    memcpy(&tx_frame_buffer[HAPTIC_FRAME_HEADER_SIZE], payload, length);
  }
  tx_frame_buffer[HAPTIC_FRAME_HEADER_SIZE + length] = (uint8_t)(crc & 0xFFU);
  tx_frame_buffer[HAPTIC_FRAME_HEADER_SIZE + length + 1U] = (uint8_t)(crc >> 8);
  HapticUsb_Write(tx_frame_buffer, (uint16_t)(HAPTIC_FRAME_HEADER_SIZE + length + HAPTIC_FRAME_CRC_SIZE));
  tx_sequence++;
}

static void send_error(const char *message) {
  send_frame(HAPTIC_MSG_ERROR, (const uint8_t *)message, (uint16_t)strlen(message));
}

static void put_u16_le(uint8_t *buffer, uint16_t offset, uint16_t value) {
  buffer[offset] = (uint8_t)(value & 0xFFU);
  buffer[offset + 1U] = (uint8_t)(value >> 8);
}

static void put_i16_le(uint8_t *buffer, uint16_t offset, int16_t value) {
  put_u16_le(buffer, offset, (uint16_t)value);
}

static void put_u32_le(uint8_t *buffer, uint16_t offset, uint32_t value) {
  buffer[offset] = (uint8_t)(value & 0xFFUL);
  buffer[offset + 1U] = (uint8_t)((value >> 8) & 0xFFUL);
  buffer[offset + 2U] = (uint8_t)((value >> 16) & 0xFFUL);
  buffer[offset + 3U] = (uint8_t)((value >> 24) & 0xFFUL);
}

static void put_i32_le(uint8_t *buffer, uint16_t offset, int32_t value) {
  put_u32_le(buffer, offset, (uint32_t)value);
}

static void acquisition_dma_complete(bool ok, void *user) {
  (void)user;
  acq_dma_ok = ok;
  acq_dma_ready = true;
  acq_dma_inflight = false;
}

static void render_dma_complete(bool ok, void *user) {
  (void)user;
  render_dma_ok = ok;
  render_dma_done = true;
  render_dma_inflight = false;
}

static void append_acquisition_samples(uint16_t *raw, uint8_t count, bool adjacent, uint8_t start_pin) {
  if (count == 0U) {
    return;
  }
  if ((uint16_t)acquisition_payload_samples + count > (HAPTIC_MAX_BINARY_PAYLOAD / sizeof(int16_t))) {
    flush_acquisition_frame();
  }
  for (uint8_t i = 0; i < count; i++) {
    uint8_t pin = adjacent ? (uint8_t)(start_pin + i) : stream_pins[i];
    channels[pin].last_value = raw[i];
    acquisition_payload[acquisition_payload_samples++] = (int16_t)(((int16_t)raw[i] - 2048) << 4);
  }
  uint32_t now = micros_now();
  if (
    acquisition_payload_samples >= (HAPTIC_MAX_BINARY_PAYLOAD / sizeof(int16_t)) ||
    (uint32_t)(now - last_acquisition_flush_us) >= ACQ_FLUSH_INTERVAL_US
  ) {
    flush_acquisition_frame();
  }
}

static void flush_acquisition_frame(void) {
  if (acquisition_payload_samples == 0U) {
    return;
  }
  send_frame(
    HAPTIC_MSG_SAMPLES,
    (const uint8_t *)acquisition_payload,
    (uint16_t)(acquisition_payload_samples * sizeof(int16_t))
  );
  acquisition_payload_samples = 0;
  last_acquisition_flush_us = micros_now();
}

static void flush_imu_frame(void) {
  if (imu_payload_samples == 0U) {
    return;
  }
  send_frame(
    HAPTIC_MSG_IMU_SAMPLES,
    imu_payload,
    (uint16_t)(imu_payload_samples * IMU_SAMPLE_PAYLOAD_SIZE)
  );
  imu_payload_samples = 0;
  last_imu_flush_us = micros_now();
}

static void append_imu_sample(const ImuSample *sample, bool ok, uint32_t timestamp_us) {
  if (sample == NULL) {
    return;
  }
  if (imu_payload_samples >= IMU_MAX_BATCH_SAMPLES) {
    flush_imu_frame();
  }

  uint16_t offset = (uint16_t)(imu_payload_samples * IMU_SAMPLE_PAYLOAD_SIZE);
  uint8_t flags = 0U;
  if (ok) {
    flags |= 0x01U;
  }
  if (sample->status.accel_ok) {
    flags |= 0x02U;
  }
  if (sample->status.gyro_ok) {
    flags |= 0x04U;
  }
  if (sample->status.mag_ok) {
    flags |= 0x08U;
  }
  if (sample->status.bmp_ok) {
    flags |= 0x10U;
  }

  put_u32_le(imu_payload, offset, timestamp_us);
  imu_payload[offset + 4U] = flags;
  imu_payload[offset + 5U] = 0U;
  put_i16_le(imu_payload, (uint16_t)(offset + 6U), sample->accel[0]);
  put_i16_le(imu_payload, (uint16_t)(offset + 8U), sample->accel[1]);
  put_i16_le(imu_payload, (uint16_t)(offset + 10U), sample->accel[2]);
  put_i16_le(imu_payload, (uint16_t)(offset + 12U), sample->gyro[0]);
  put_i16_le(imu_payload, (uint16_t)(offset + 14U), sample->gyro[1]);
  put_i16_le(imu_payload, (uint16_t)(offset + 16U), sample->gyro[2]);
  put_i16_le(imu_payload, (uint16_t)(offset + 18U), sample->mag[0]);
  put_i16_le(imu_payload, (uint16_t)(offset + 20U), sample->mag[1]);
  put_i16_le(imu_payload, (uint16_t)(offset + 22U), sample->mag[2]);
  put_i32_le(imu_payload, (uint16_t)(offset + 24U), sample->bmp_pressure_raw);
  put_i32_le(imu_payload, (uint16_t)(offset + 28U), sample->bmp_temperature_raw);
  imu_payload_samples++;

  uint32_t now = micros_now();
  if (imu_payload_samples >= IMU_MAX_BATCH_SAMPLES || (uint32_t)(now - last_imu_flush_us) >= IMU_FLUSH_INTERVAL_US) {
    flush_imu_frame();
  }
}

static void reset_channels(void) {
  for (uint8_t i = 0; i < CHANNEL_COUNT; i++) {
    channels[i].role = ROLE_HIGH_Z;
    channels[i].partner = -1;
    channels[i].adc_range = MAX_ADC_RANGE_0_2_5;
    channels[i].dac_range = MAX_DAC_RANGE_0_10;
    channels[i].averaging = 1;
    channels[i].stream = false;
    channels[i].last_value = 0;
  }
  stream_pin_count = 0;
  output_pin_count = 0;
  stream_pins_are_adjacent = false;
  output_pins_are_adjacent = false;
}

static void rebuild_active_pin_lists(void) {
  stream_pin_count = 0;
  output_pin_count = 0;
  for (uint8_t pin = 0; pin < CHANNEL_COUNT; pin++) {
    if (channels[pin].stream && (channels[pin].role == ROLE_INPUT || channels[pin].role == ROLE_DIFFERENTIAL)) {
      stream_pins[stream_pin_count++] = pin;
    }
    if (channels[pin].role == ROLE_OUTPUT) {
      output_pins[output_pin_count++] = pin;
    }
  }

  stream_pins_are_adjacent = stream_pin_count > 0U;
  stream_span_start = stream_pin_count > 0U ? stream_pins[0] : 0U;
  stream_span_count = stream_pin_count;
  for (uint8_t i = 1; i < stream_pin_count; i++) {
    if (stream_pins[i] != (uint8_t)(stream_pins[i - 1U] + 1U)) {
      stream_pins_are_adjacent = false;
    }
  }

  output_pins_are_adjacent = output_pin_count > 0U;
  output_span_start = output_pin_count > 0U ? output_pins[0] : 0U;
  output_span_count = output_pin_count;
  for (uint8_t i = 1; i < output_pin_count; i++) {
    if (output_pins[i] != (uint8_t)(output_pins[i - 1U] + 1U)) {
      output_pins_are_adjacent = false;
    }
  }
}

static ChannelRole parse_role(const char *role) {
  if (strcmp(role, "input") == 0) {
    return ROLE_INPUT;
  }
  if (strcmp(role, "output") == 0) {
    return ROLE_OUTPUT;
  }
  if (strcmp(role, "differential") == 0) {
    return ROLE_DIFFERENTIAL;
  }
  return ROLE_HIGH_Z;
}

static uint16_t parse_adc_range(const char *range, uint16_t fallback) {
  if (range == NULL) {
    return fallback;
  }
  if (strcmp(range, "0_10") == 0) {
    return MAX_ADC_RANGE_0_10;
  }
  if (strcmp(range, "5_5") == 0) {
    return MAX_ADC_RANGE_5_5;
  }
  if (strcmp(range, "10_0") == 0) {
    return MAX_ADC_RANGE_10_0;
  }
  if (strcmp(range, "0_2_5") == 0) {
    return MAX_ADC_RANGE_0_2_5;
  }
  return fallback;
}

static uint16_t parse_dac_range(const char *range, uint16_t fallback) {
  if (range == NULL) {
    return fallback;
  }
  if (strcmp(range, "0_10") == 0) {
    return MAX_DAC_RANGE_0_10;
  }
  if (strcmp(range, "5_5") == 0) {
    return MAX_DAC_RANGE_5_5;
  }
  if (strcmp(range, "10_0") == 0) {
    return MAX_DAC_RANGE_10_0;
  }
  return fallback;
}

static void apply_channel(uint8_t pin) {
  if (!pixi_ok || pin >= CHANNEL_COUNT) {
    return;
  }
  ChannelState *ch = &channels[pin];
  if (ch->role == ROLE_INPUT) {
    Max11300_SetPinMode(&pixi, pin, MAX_PIN_ADC, -1);
    Max11300_SetPinAdcRange(&pixi, pin, ch->adc_range);
    Max11300_SetPinAveraging(&pixi, pin, ch->averaging);
  } else if (ch->role == ROLE_OUTPUT) {
    Max11300_SetPinMode(&pixi, pin, MAX_PIN_DAC, -1);
    Max11300_SetPinDacRange(&pixi, pin, ch->dac_range);
    /* Render outputs idle at 2.5 V in the 0 V to 10 V range. */
    Max11300_WriteAnalogPin(&pixi, pin, DAC_RENDER_BIAS_CODE);
  } else if (ch->role == ROLE_DIFFERENTIAL && ch->partner >= 0) {
    Max11300_SetPinMode(&pixi, pin, MAX_PIN_ADC_DIFF_POS, ch->partner);
    Max11300_SetPinAdcRange(&pixi, pin, ch->adc_range);
  } else {
    Max11300_SetPinMode(&pixi, pin, MAX_PIN_HIGH_Z, -1);
  }
}

static void send_status(void) {
  ImuStatus imu = Imu_GetStatus();
  uint16_t rx_queue_bytes = HapticUsb_Available();
  static char text[768];
  snprintf(
    text,
    sizeof(text),
    "STATUS {\"firmware\":\"" HAPTIC_VERSION "\",\"pixi_ok\":%s,\"acquiring\":%s,"
    "\"rendering\":%s,\"imu_ok\":%s,\"imu_stream\":%s,\"imu_rate\":%lu,"
    "\"sample_rate\":%lu,\"dropped_frames\":%lu,"
    "\"underruns\":%lu,\"render_startup_underruns\":%lu,\"render_overruns\":%lu,"
    "\"render_overvolts\":%lu,\"render_fill\":%u,"
    "\"render_samples\":%lu,\"render_bias_samples\":%lu,\"render_underrun_bias_samples\":%lu,"
    "\"render_late_ticks\":%lu,\"render_due_max\":%u,"
    "\"render_spi_failures\":%lu,\"render_tick_max_us\":%lu,"
    "\"rx_queue_bytes\":%u,\"rx_queue_max\":%u}\n",
    pixi_ok ? "true" : "false",
    acquiring ? "true" : "false",
    rendering ? "true" : "false",
    (imu.accel_ok || imu.gyro_ok || imu.mag_ok || imu.bmp_ok) ? "true" : "false",
    imu_stream_enabled ? "true" : "false",
    (unsigned long)imu_stream_rate_hz,
    (unsigned long)sample_rate_hz,
    (unsigned long)dropped_frames,
    (unsigned long)underruns,
    (unsigned long)render_startup_underruns,
    (unsigned long)render_overruns,
    (unsigned long)render_overvolts,
    (unsigned int)render_fill(),
    (unsigned long)render_samples,
    (unsigned long)render_bias_samples,
    (unsigned long)render_underrun_bias_samples,
    (unsigned long)render_late_ticks,
    (unsigned int)render_due_max,
    (unsigned long)render_spi_failures,
    (unsigned long)render_tick_max_us,
    (unsigned int)rx_queue_bytes,
    (unsigned int)rx_queue_max
  );
  HapticUsb_WriteText(text);
}

static void send_imu_status(void) {
  ImuStatus imu = Imu_GetStatus();
  char text[160];
  snprintf(
    text,
    sizeof(text),
    "OK IMU_STATUS {\"accel_ok\":%s,\"gyro_ok\":%s,\"mag_ok\":%s,"
    "\"bmp_ok\":%s,\"bmp_addr\":%u}\n",
    imu.accel_ok ? "true" : "false",
    imu.gyro_ok ? "true" : "false",
    imu.mag_ok ? "true" : "false",
    imu.bmp_ok ? "true" : "false",
    (unsigned int)imu.bmp_addr
  );
  HapticUsb_WriteText(text);
}

static void send_imu_read(void) {
  ImuSample sample;
  bool ok = Imu_Read(&sample);
  char text[320];
  snprintf(
    text,
    sizeof(text),
    "OK IMU_READ {\"ok\":%s,\"accel_ok\":%s,\"gyro_ok\":%s,\"mag_ok\":%s,"
    "\"bmp_ok\":%s,\"accel\":[%d,%d,%d],\"gyro\":[%d,%d,%d],"
    "\"mag\":[%d,%d,%d],\"bmp_pressure_raw\":%ld,\"bmp_temperature_raw\":%ld}\n",
    ok ? "true" : "false",
    sample.status.accel_ok ? "true" : "false",
    sample.status.gyro_ok ? "true" : "false",
    sample.status.mag_ok ? "true" : "false",
    sample.status.bmp_ok ? "true" : "false",
    sample.accel[0], sample.accel[1], sample.accel[2],
    sample.gyro[0], sample.gyro[1], sample.gyro[2],
    sample.mag[0], sample.mag[1], sample.mag[2],
    (long)sample.bmp_pressure_raw,
    (long)sample.bmp_temperature_raw
  );
  HapticUsb_WriteText(text);
}

static void configure_stream(char *args) {
  flush_acquisition_frame();
  char *rate_token = strtok(args, " ");
  char *channels_token = strtok(NULL, " ");
  if (rate_token != NULL) {
    sample_rate_hz = strtoul(rate_token, NULL, 10);
    if (sample_rate_hz == 0UL) {
      sample_rate_hz = 1UL;
    }
    sample_interval_us = 1000000UL / sample_rate_hz;
    if (sample_interval_us == 0UL) {
      sample_interval_us = 1UL;
    }
    sample_timer_configure();
    sample_timer_update_state();
  }
  for (uint8_t i = 0; i < CHANNEL_COUNT; i++) {
    channels[i].stream = false;
  }
  if (channels_token != NULL) {
    char *pin_token = strtok(channels_token, ",");
    while (pin_token != NULL) {
      uint8_t pin = (uint8_t)atoi(pin_token);
      if (pin < CHANNEL_COUNT) {
        channels[pin].stream = true;
      }
      pin_token = strtok(NULL, ",");
    }
  }
  rebuild_active_pin_lists();
  HapticUsb_WriteText("OK CONFIG_STREAM\n");
}

static void configure_imu_stream(char *args) {
  char *rate_token = strtok(args, " ");
  char *enable_token = strtok(NULL, " ");
  char *mask_token = strtok(NULL, " ");
  if (mask_token != NULL) {
    uint8_t requested_mask = (uint8_t)strtoul(mask_token, NULL, 0) & IMU_SELECT_ALL;
    if (requested_mask != 0U) {
      imu_sensor_mask = requested_mask;
    }
  }
  if (rate_token != NULL) {
    imu_stream_rate_hz = strtoul(rate_token, NULL, 10);
    if (imu_stream_rate_hz == 0UL) {
      imu_stream_rate_hz = DEFAULT_IMU_STREAM_RATE_HZ;
    }
    uint32_t maximum_rate_hz = max_imu_rate_for_mask(imu_sensor_mask);
    if (imu_stream_rate_hz > maximum_rate_hz) {
      imu_stream_rate_hz = maximum_rate_hz;
    }
    (void)Imu_SetAccelRate(imu_stream_rate_hz);
    imu_stream_interval_us = 1000000UL / imu_stream_rate_hz;
    if (imu_stream_interval_us == 0UL) {
      imu_stream_interval_us = 1UL;
    }
  }
  if (enable_token != NULL) {
    imu_stream_enabled = atoi(enable_token) != 0;
    if (!imu_stream_enabled) {
      flush_imu_frame();
    }
  }
  next_imu_stream_us = micros_now();
  HapticUsb_WriteText("OK CONFIG_IMU_STREAM\n");
}

static void configure_channel(char *args) {
  char *pin_token = strtok(args, " ");
  char *role_token = strtok(NULL, " ");
  char *partner_token = strtok(NULL, " ");
  char *adc_range_token = strtok(NULL, " ");
  char *dac_range_token = strtok(NULL, " ");
  strtok(NULL, " ");
  char *avg_token = strtok(NULL, " ");
  char *stream_token = strtok(NULL, " ");
  if (pin_token == NULL || role_token == NULL) {
    HapticUsb_WriteText("ERR CONFIG_CHANNEL missing_args\n");
    return;
  }
  uint8_t pin = (uint8_t)atoi(pin_token);
  if (pin >= CHANNEL_COUNT) {
    HapticUsb_WriteText("ERR CONFIG_CHANNEL bad_pin\n");
    return;
  }
  channels[pin].role = parse_role(role_token);
  channels[pin].partner = (partner_token != NULL && strcmp(partner_token, "-") != 0) ? (int8_t)atoi(partner_token) : -1;
  channels[pin].adc_range = parse_adc_range(adc_range_token, channels[pin].adc_range);
  channels[pin].dac_range = parse_dac_range(dac_range_token, channels[pin].dac_range);
  channels[pin].averaging = avg_token != NULL ? (uint8_t)atoi(avg_token) : 1U;
  if (channels[pin].averaging == 0U) {
    channels[pin].averaging = 1U;
  }
  channels[pin].stream = stream_token != NULL ? atoi(stream_token) != 0 : false;
  apply_channel(pin);
  rebuild_active_pin_lists();
  HapticUsb_WriteText("OK CONFIG_CHANNEL\n");
}

static void run_dac_test(char *args) {
  char *pin_token = strtok(args, " ");
  char *millivolts_token = strtok(NULL, " ");
  if (pin_token == NULL || millivolts_token == NULL) {
    HapticUsb_WriteText("ERR DAC_TEST usage: DAC_TEST <pin> <2200|2500|2800>\n");
    return;
  }

  char *pin_end = NULL;
  char *millivolts_end = NULL;
  long pin_value = strtol(pin_token, &pin_end, 10);
  long millivolts = strtol(millivolts_token, &millivolts_end, 10);
  if (
    pin_end == pin_token || *pin_end != '\0' ||
    pin_value < 0L || pin_value >= CHANNEL_COUNT
  ) {
    HapticUsb_WriteText("ERR DAC_TEST bad_pin\n");
    return;
  }
  if (
    millivolts_end == millivolts_token || *millivolts_end != '\0' ||
    (millivolts != 2200L && millivolts != 2500L && millivolts != 2800L)
  ) {
    HapticUsb_WriteText("ERR DAC_TEST voltage_must_be_2200_2500_or_2800_mV\n");
    return;
  }
  if (!pixi_ok) {
    HapticUsb_WriteText("ERR DAC_TEST pixi_not_ready\n");
    return;
  }

  stop_rendering_idle(true);

  uint8_t pin = (uint8_t)pin_value;
  channels[pin].role = ROLE_OUTPUT;
  channels[pin].partner = -1;
  channels[pin].dac_range = MAX_DAC_RANGE_0_10;
  channels[pin].stream = false;
  apply_channel(pin);
  rebuild_active_pin_lists();

  uint16_t dac_code = dac_code_from_0_10_millivolts(millivolts);
  if (!Max11300_WriteAnalogPin(&pixi, pin, (uint16_t)dac_code)) {
    HapticUsb_WriteText("ERR DAC_TEST write_failed\n");
    return;
  }

  uint16_t device_control = Max11300_ReadRegister(&pixi, MAX_DEVCTL);
  uint16_t port_config = Max11300_ReadRegister(&pixi, (uint8_t)(MAX_FUNC_BASE + pin));
  uint16_t data_readback = Max11300_ReadRegister(&pixi, (uint8_t)(MAX_DACDAT_BASE + pin));
  char response[128];
  snprintf(
    response,
    sizeof(response),
    "OK DAC_TEST pin=%ld millivolts=%ld code=%u devctl=0x%04X portcfg=0x%04X readback=%u\n",
    pin_value,
    millivolts,
    (unsigned int)dac_code,
    (unsigned int)device_control,
    (unsigned int)port_config,
    (unsigned int)data_readback
  );
  HapticUsb_WriteText(response);
}

static void run_dac_sine_test(char *args) {
  char *pin_token = strtok(args, " ");
  char *freq_token = strtok(NULL, " ");
  char *duration_token = strtok(NULL, " ");

  if (pin_token == NULL) {
    HapticUsb_WriteText("ERR DAC_SINE_TEST usage: DAC_SINE_TEST <pin> [freq_hz] [duration_ms]\n");
    return;
  }

  char *pin_end = NULL;
  long pin_value = strtol(pin_token, &pin_end, 10);
  if (
    pin_end == pin_token || *pin_end != '\0' ||
    pin_value < 0L || pin_value >= CHANNEL_COUNT
  ) {
    HapticUsb_WriteText("ERR DAC_SINE_TEST bad_pin\n");
    return;
  }

  long freq_hz = DAC_SINE_TEST_DEFAULT_FREQ_HZ;
  if (freq_token != NULL) {
    char *freq_end = NULL;
    freq_hz = strtol(freq_token, &freq_end, 10);
    if (freq_end == freq_token || *freq_end != '\0' || freq_hz <= 0L || freq_hz > 1000L) {
      HapticUsb_WriteText("ERR DAC_SINE_TEST freq_must_be_1_to_1000_Hz\n");
      return;
    }
  }

  long duration_ms = DAC_SINE_TEST_DEFAULT_DURATION_MS;
  if (duration_token != NULL) {
    char *duration_end = NULL;
    duration_ms = strtol(duration_token, &duration_end, 10);
    if (duration_end == duration_token || *duration_end != '\0' || duration_ms <= 0L || duration_ms > 30000L) {
      HapticUsb_WriteText("ERR DAC_SINE_TEST duration_must_be_1_to_30000_ms\n");
      return;
    }
  }

  if (!pixi_ok) {
    HapticUsb_WriteText("ERR DAC_SINE_TEST pixi_not_ready\n");
    return;
  }

  stop_rendering_idle(true);

  uint8_t pin = (uint8_t)pin_value;
  channels[pin].role = ROLE_OUTPUT;
  channels[pin].partner = -1;
  channels[pin].dac_range = MAX_DAC_RANGE_0_10;
  channels[pin].stream = false;
  apply_channel(pin);
  rebuild_active_pin_lists();

  uint32_t sample_interval_us_local = 1000000UL / DAC_SINE_TEST_SAMPLE_RATE_HZ;
  uint32_t total_samples = ((uint32_t)duration_ms * DAC_SINE_TEST_SAMPLE_RATE_HZ) / 1000UL;
  uint32_t phase = 0;
  uint32_t phase_step = ((uint32_t)freq_hz * DAC_SINE_TEST_TABLE_SIZE);
  uint32_t next_us = micros_now();

  for (uint32_t sample = 0; sample < total_samples; sample++) {
    uint16_t table_index = (uint16_t)((phase / DAC_SINE_TEST_SAMPLE_RATE_HZ) % DAC_SINE_TEST_TABLE_SIZE);
    int32_t dac_code = (int32_t)DAC_RENDER_BIAS_CODE +
      (((int32_t)dac_sine_table[table_index] * DAC_RENDER_LIMIT_DELTA_CODE) / 3070L);
    if (dac_code < 0L) {
      dac_code = 0L;
    } else if (dac_code > 4095L) {
      dac_code = 4095L;
    }
    Max11300_WriteAnalogPin(&pixi, pin, (uint16_t)dac_code);

    phase += phase_step;
    next_us += sample_interval_us_local;
    while ((int32_t)(micros_now() - next_us) < 0) {
      /* Blocking diagnostic: keep timing deterministic until the test ends. */
    }
  }

  Max11300_WriteAnalogPin(&pixi, pin, DAC_RENDER_BIAS_CODE);

  char response[128];
  snprintf(
    response,
    sizeof(response),
    "OK DAC_SINE_TEST pin=%ld freq_hz=%ld duration_ms=%ld sample_rate=%lu bias_code=%u amplitude_codes=%ld\n",
    pin_value,
    freq_hz,
    duration_ms,
    (unsigned long)DAC_SINE_TEST_SAMPLE_RATE_HZ,
    (unsigned int)DAC_RENDER_BIAS_CODE,
    (long)DAC_RENDER_LIMIT_DELTA_CODE
  );
  HapticUsb_WriteText(response);
}

static void handle_command(char *line) {
  char *cmd = strtok(line, " ");
  char *args = strtok(NULL, "");
  if (cmd == NULL) {
    return;
  }
  if (strcmp(cmd, "HELLO") == 0) {
    HapticUsb_WriteText("OK HELLO " HAPTIC_VERSION "\n");
  } else if (strcmp(cmd, "PING") == 0) {
    HapticUsb_WriteText("OK PONG\n");
  } else if (strcmp(cmd, "STATUS") == 0 || strcmp(cmd, "GET_CHANNELS") == 0) {
    send_status();
  } else if (strcmp(cmd, "IMU_STATUS") == 0) {
    send_imu_status();
  } else if (strcmp(cmd, "IMU_READ") == 0) {
    send_imu_read();
  } else if (strcmp(cmd, "CONFIG_STREAM") == 0) {
    char empty[] = "";
    configure_stream(args != NULL ? args : empty);
  } else if (strcmp(cmd, "CONFIG_IMU_STREAM") == 0) {
    char empty[] = "";
    configure_imu_stream(args != NULL ? args : empty);
  } else if (strcmp(cmd, "CONFIG_CHANNEL") == 0) {
    char empty[] = "";
    configure_channel(args != NULL ? args : empty);
  } else if (strcmp(cmd, "DAC_TEST") == 0) {
    char empty[] = "";
    run_dac_test(args != NULL ? args : empty);
  } else if (strcmp(cmd, "DAC_SINE_TEST") == 0) {
    char empty[] = "";
    run_dac_sine_test(args != NULL ? args : empty);
  } else if (strcmp(cmd, "START_ACQ") == 0) {
    acquisition_payload_samples = 0;
    dropped_frames = 0;
    acquisition_due = 0;
    next_imu_stream_us = micros_now();
    last_imu_flush_us = next_imu_stream_us;
    imu_payload_samples = 0;
    acquiring = true;
    if (pixi_ok) {
      Max11300_SetAdcMode(&pixi, MAX_ADC_CONTINUOUS);
    }
    sample_timer_update_state();
    HapticUsb_WriteText("OK START_ACQ\n");
  } else if (strcmp(cmd, "STOP_ACQ") == 0) {
    flush_acquisition_frame();
    flush_imu_frame();
    acquiring = false;
    acquisition_due = 0;
    next_imu_stream_us = 0;
    sample_timer_update_state();
    HapticUsb_WriteText("OK STOP_ACQ\n");
  } else if (strcmp(cmd, "START_RENDER") == 0) {
    underruns = 0;
    render_startup_underruns = 0;
    render_overruns = 0;
    dropped_frames = 0;
    render_overvolts = 0;
    render_samples = 0;
    render_bias_samples = 0;
    render_underrun_bias_samples = 0;
    render_late_ticks = 0;
    render_spi_failures = 0;
    render_tick_max_us = 0;
    render_due_max = 0;
    rx_queue_max = HapticUsb_Available();
    consecutive_render_underruns = 0;
    /*
     * Prefilled samples bridge the START_RENDER command round trip. Keep
     * classifying any gap as startup latency until the first OUTPUT_BUFFER
     * frame received after rendering has started.
     */
    render_data_received = false;
    render_due = 0;
    /*
     * Do not clear the render ring here: the host pre-fills OUTPUT_BUFFER
     * frames before START_RENDER so playback can begin without underruns.
     * STOP_RENDER clears stale samples after playback has stopped.
     */
    rendering = true;
    sample_timer_update_state();
    HapticUsb_WriteText("OK START_RENDER\n");
  } else if (strcmp(cmd, "STOP_RENDER") == 0) {
    stop_rendering_idle(false);
    HapticUsb_WriteText("OK STOP_RENDER\n");
    if (pixi_ok) {
      for (uint8_t i = 0; i < output_pin_count; i++) {
        Max11300_WriteAnalogPin(&pixi, output_pins[i], DAC_RENDER_BIAS_CODE);
      }
    }
  } else {
    HapticUsb_WriteText("ERR unknown_command\n");
  }
}

static void handle_output_frame(uint8_t type, uint8_t *payload, uint16_t length) {
  if (type == HAPTIC_MSG_OUTPUT_BUFFER) {
    for (uint16_t i = 0; i + 1U < length; i = (uint16_t)(i + 2U)) {
      int16_t signed_sample = (int16_t)(payload[i] | ((uint16_t)payload[i + 1U] << 8));
      uint16_t dac = limited_render_dac_code(signed_sample);
      push_render(dac);
    }
  } else if (type == HAPTIC_MSG_LOOPBACK) {
    pending_loopback_length = length > sizeof(pending_loopback) ? sizeof(pending_loopback) : length;
    memcpy(pending_loopback, payload, pending_loopback_length);
    loopback_pending = true;
  }
}

static void parse_byte(uint8_t byte) {
  if (parse_state == PARSE_TEXT) {
    if (byte == HAPTIC_SYNC0) {
      frame_header[0] = byte;
      header_index = 1;
      parse_state = PARSE_SYNC1;
    } else if (byte == '\r') {
      return;
    } else if (byte == '\n') {
      line_buffer[line_length] = '\0';
      handle_command(line_buffer);
      line_length = 0;
    } else if (line_length < (LINE_BUFFER_SIZE - 1U)) {
      line_buffer[line_length++] = (char)byte;
    } else {
      line_length = 0;
      HapticUsb_WriteText("ERR command_too_long\n");
    }
  } else if (parse_state == PARSE_SYNC1) {
    if (byte != HAPTIC_SYNC1) {
      parse_state = PARSE_TEXT;
      line_length = 0;
      return;
    }
    frame_header[header_index++] = byte;
    parse_state = PARSE_HEADER;
  } else if (parse_state == PARSE_HEADER) {
    frame_header[header_index++] = byte;
    if (header_index == HAPTIC_FRAME_HEADER_SIZE) {
      frame_type = frame_header[2];
      frame_length = (uint16_t)(frame_header[3] | ((uint16_t)frame_header[4] << 8));
      if (frame_length > HAPTIC_MAX_BINARY_PAYLOAD) {
        send_error("frame too large");
        discard_remaining = (uint16_t)(frame_length + HAPTIC_FRAME_CRC_SIZE);
        parse_state = PARSE_DISCARD;
      } else {
        frame_index = 0;
        parse_state = frame_length > 0U ? PARSE_PAYLOAD : PARSE_CRC;
      }
    }
  } else if (parse_state == PARSE_PAYLOAD) {
    frame_payload[frame_index++] = byte;
    if (frame_index >= frame_length) {
      frame_index = 0;
      parse_state = PARSE_CRC;
    }
  } else if (parse_state == PARSE_CRC) {
    if (frame_index == 0U) {
      received_crc = byte;
      frame_index = 1;
    } else {
      received_crc |= (uint16_t)byte << 8;
      uint16_t calc = HapticProtocol_Crc16(frame_header, HAPTIC_FRAME_HEADER_SIZE);
      for (uint16_t i = 0; i < frame_length; i++) {
        calc = HapticProtocol_Crc16Update(calc, frame_payload[i]);
      }
      if (calc == received_crc) {
        handle_output_frame(frame_type, frame_payload, frame_length);
      } else {
        send_error("crc failure");
      }
      parse_state = PARSE_TEXT;
      frame_index = 0;
    }
  } else if (parse_state == PARSE_DISCARD) {
    if (discard_remaining > 0U) {
      discard_remaining--;
    }
    if (discard_remaining == 0U) {
      parse_state = PARSE_TEXT;
    }
  }
}

static void process_rx(void) {
  uint8_t byte = 0;
  uint16_t processed = 0;
  uint16_t budget = RX_BYTES_PER_TICK_IDLE;
  uint16_t available = HapticUsb_Available();
  if (available > rx_queue_max) {
    rx_queue_max = available;
  }
  while (processed < budget && HapticUsb_ReadByte(&byte)) {
    parse_byte(byte);
    processed++;

    /* Always process at least one byte, then yield for rendering. */
    if (rendering && render_due > 0U) {
      break;
    }
  }
}

static void loopback_tick(void) {
  if (!loopback_pending) {
    return;
  }
  loopback_pending = false;
  send_frame(HAPTIC_MSG_LOOPBACK, pending_loopback, pending_loopback_length);
}

static void process_acquisition_dma(void) {
  if (!acq_dma_ready) {
    return;
  }

  __disable_irq();
  bool ok = acq_dma_ok;
  uint8_t count = acq_dma_count;
  bool adjacent = acq_dma_adjacent;
  uint8_t start_pin = acq_dma_start_pin;
  acq_dma_ready = false;
  __enable_irq();

  if (!ok) {
    send_error("adc dma failure");
    return;
  }
  append_acquisition_samples(acq_dma_raw, count, adjacent, start_pin);
}

/*
process_render_dma(void)
exists solely to report failures safely outside the interrupt callback
*/ 
static void process_render_dma(void) {
  if (!render_dma_done) {
    return;
  }
  __disable_irq();
  bool ok = render_dma_ok;
  render_dma_done = false;
  __enable_irq();
  if (!ok) {
    send_error("dac dma failure");
  }
}

static void acquisition_tick(void) {
  if (!acquiring) {
    return;
  }
  uint8_t catchup = 0;
  while (catchup < MAX_SCHEDULER_CATCHUP) {
    if (acquisition_due == 0U) {
      break;
    }
    __disable_irq();
    if (acquisition_due > 0U) {
      acquisition_due--;
    }
    __enable_irq();
    catchup++;
    if (!pixi_ok) {
      acq_dma_start_pin = stream_pin_count > 0U ? stream_pins[0] : 0U;
      acq_dma_count = stream_pin_count;
      acq_dma_adjacent = false;
      for (uint8_t i = 0; i < acq_dma_count; i++) {
        acq_dma_raw[i] = 2048U;
      }
      append_acquisition_samples(acq_dma_raw, acq_dma_count, false, acq_dma_start_pin);
      break;
    }
    if (stream_pins_are_adjacent && stream_span_count > 1U) {
      acq_dma_start_pin = stream_span_start;
      acq_dma_count = stream_span_count;
      acq_dma_adjacent = true;
      if (stream_span_count >= MIN_DMA_BURST_WORDS) {
        if (acq_dma_inflight || Max11300_IsDmaBusy()) {
          acquisition_due++;
          break;
        }
        acq_dma_inflight = true;
        if (!Max11300_ReadRegistersDma(&pixi, (uint8_t)(MAX_ADCDAT_BASE + stream_span_start), acq_dma_raw, stream_span_count, acquisition_dma_complete, 0)) {
          acq_dma_inflight = false;
          send_error("adc dma start failure");
        }
      } else {
        Max11300_BurstAnalogRead(&pixi, stream_span_start, acq_dma_raw, stream_span_count);
        append_acquisition_samples(acq_dma_raw, stream_span_count, true, stream_span_start);
      }
    } else {
      if (stream_pin_count == 0U) {
        continue;
      }
      if (stream_pin_count > 1U) {
        uint8_t count = 0;
        for (uint8_t i = 0; i < stream_pin_count; i++) {
          uint8_t pin = stream_pins[i];
          acq_dma_raw[count++] = Max11300_ReadAnalogPin(&pixi, pin);
        }
        acq_dma_start_pin = stream_pins[0];
        acq_dma_count = count;
        acq_dma_adjacent = false;
        append_acquisition_samples(acq_dma_raw, count, false, acq_dma_start_pin);
        break;
      }
      acq_dma_start_pin = stream_pins[0];
      acq_dma_count = 1U;
      acq_dma_adjacent = false;
      acq_dma_raw[0] = Max11300_ReadAnalogPin(&pixi, stream_pins[0]);
      append_acquisition_samples(acq_dma_raw, 1U, false, acq_dma_start_pin);
    }
  }
}

static void imu_stream_tick(void) {
  if (!acquiring || !imu_stream_enabled) {
    if (imu_payload_samples > 0U) {
      flush_imu_frame();
    }
    return;
  }
  uint32_t now = micros_now();
  if (next_imu_stream_us == 0U) {
    next_imu_stream_us = now;
  }
  if ((int32_t)(now - next_imu_stream_us) < 0) {
    if (imu_payload_samples > 0U && (uint32_t)(now - last_imu_flush_us) >= IMU_FLUSH_INTERVAL_US) {
      flush_imu_frame();
    }
    return;
  }

  ImuSample sample;
  bool ok = Imu_ReadSelected(&sample, imu_sensor_mask);
  append_imu_sample(&sample, ok, now);

  do {
    next_imu_stream_us += imu_stream_interval_us;
  } while ((int32_t)(now - next_imu_stream_us) >= 0);
}

static void render_tick(void) {
  if (!rendering) {
    return;
  }
  uint32_t tick_started_us = micros_now();
  uint8_t catchup = 0;
  while (catchup < MAX_RENDER_CATCHUP) {
    if (render_due == 0U) {
      break;
    }
    if (render_due > render_due_max) {
      render_due_max = render_due;
    }
    if (render_due > 1U) {
      render_late_ticks++;
    }
    __disable_irq();
    if (render_due > 0U) {
      render_due--;
    }
    __enable_irq();
    catchup++;

    uint16_t value = DAC_RENDER_BIAS_CODE;
    bool had_sample = pop_render(&value);
    if (!had_sample) {
      underruns++;
      if (!render_data_received) {
        render_startup_underruns++;
      }
      render_underrun_bias_samples++;
      consecutive_render_underruns++;
      if (consecutive_render_underruns >= RENDER_MAX_CONSECUTIVE_UNDERRUNS) {
        stop_rendering_idle(true);
        break;
      }
    } else {
      consecutive_render_underruns = 0;
    }
    if (value == DAC_RENDER_BIAS_CODE) {
      render_bias_samples++;
    }
    render_samples++;
    if (pixi_ok && output_pins_are_adjacent && output_span_count > 1U) {
      for (uint8_t i = 0; i < output_span_count; i++) {
        render_dma_values[i] = value;
      }
      if (output_span_count >= MIN_DMA_BURST_WORDS) {
        if (render_dma_inflight || Max11300_IsDmaBusy()) {
          render_due++;
          break;
        }
        render_dma_inflight = true;
        if (!Max11300_WriteRegistersDma(&pixi, (uint8_t)(MAX_DACDAT_BASE + output_span_start), render_dma_values, output_span_count, render_dma_complete, 0)) {
          render_dma_inflight = false;
          render_spi_failures++;
          send_error("dac dma start failure");
        }
      } else {
        if (!Max11300_BurstAnalogWrite(&pixi, output_span_start, render_dma_values, output_span_count)) {
          render_spi_failures++;
        }
      }
    } else if (pixi_ok) {
      if (output_pin_count == 0U) {
        continue;
      }
      if (output_pin_count > 1U) {
        for (uint8_t i = 0; i < output_pin_count; i++) {
          if (!Max11300_WriteAnalogPin(&pixi, output_pins[i], value)) {
            render_spi_failures++;
          }
        }
        continue;
      }
      if (!Max11300_WriteAnalogPin(&pixi, output_pins[0], value)) {
        render_spi_failures++;
      }
    }
  }
  uint32_t elapsed_us = (uint32_t)(micros_now() - tick_started_us);
  if (elapsed_us > render_tick_max_us) {
    render_tick_max_us = elapsed_us;
  }
}

void HapticApp_Init(void) {
  micros_init();
  reset_channels();
  sample_timer_configure();
  Imu_Init();
  Max11300_Init(&pixi, &hspi1);
  pixi_ok = Max11300_Begin(&pixi);
  if (pixi_ok) {
    Max11300_SetConversionRate(&pixi, MAX_RATE_200);
    Max11300_SetDacRef(&pixi, MAX_DAC_REF_INTERNAL);
    Max11300_SetDacMode(&pixi, MAX_DAC_IMMEDIATE);
    Max11300_SetAdcMode(&pixi, MAX_ADC_CONTINUOUS);
  }
  last_acquisition_flush_us = micros_now();
  HapticUsb_WriteText("READY " HAPTIC_VERSION "\n");
}

void HapticApp_Tick(void) {
  process_acquisition_dma();
  process_render_dma();
  render_tick();
  acquisition_tick();
  imu_stream_tick();
  process_rx();
  loopback_tick();
}
