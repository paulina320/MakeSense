"""
Model Widget
UI for texture modeling module with FFT display and parameter controls.
"""

import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QSpinBox, QLabel, QRadioButton,
    QStackedWidget, QDoubleSpinBox, QComboBox, QCheckBox, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
import numpy as np
from scipy import signal as sp_signal
from processing.recording import Recording
from processing.texture_models import create_texture_model
from ui.model_display_widget import ModelDisplayWidget
from config.config import TEXTURE_MODEL_CONFIG
from scipy.ndimage import gaussian_filter1d
from statsmodels.tsa.arima.model import ARIMA

class ModelWidget(QWidget):
    """Widget for texture modeling module with FFT comparison."""
    
    model_updated = pyqtSignal(dict)  # model parameters
    
    def __init__(self):
        super().__init__()
        self.current_recording = None
        self.current_model_type = "Raw Signal"
        self.current_parameters = {}
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        # Add FFT display widget
        self.display_widget = ModelDisplayWidget()
        layout.addWidget(self.display_widget)
        
        # Model selection group
        model_group = QGroupBox("Model Selection")
        model_layout = QVBoxLayout()
        
        # Radio buttons for model selection
        radio_layout = QHBoxLayout()
        self.radio_buttons = {}
        
        for model_name in ["Raw Signal", "ARMA", "MFCC", "sPeak", "sBeta", "Spectral Slope"]:
            radio = QRadioButton(model_name)
            self.radio_buttons[model_name] = radio
            radio_layout.addWidget(radio)
        
        self.radio_buttons["Raw Signal"].setChecked(True)
        model_layout.addLayout(radio_layout)
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)

        preprocessing_group = QGroupBox("Preprocessing")
        preprocessing_layout = QVBoxLayout()

        preprocessing_mode_layout = QHBoxLayout()
        preprocessing_mode_layout.addWidget(QLabel("Mode:"))
        self.preprocessing_combo = QComboBox()
        self.preprocessing_combo.addItem("No preprocessing", "no_preprocessing")
        self.preprocessing_combo.addItem("Whole signal", "whole_signal")
        self.preprocessing_combo.addItem("4000-sample Hanning sweep average", "hanning_sweep_average")
        preprocessing_mode_layout.addWidget(self.preprocessing_combo)
        preprocessing_mode_layout.addStretch()
        preprocessing_layout.addLayout(preprocessing_mode_layout)


        preprocessing_group.setLayout(preprocessing_layout)
        layout.addWidget(preprocessing_group)
        
        # Parameter configuration group
        params_group = QGroupBox("Model Parameters")
        params_layout = QVBoxLayout()
        
        # Stacked widget for different parameter sets
        self.param_stack = QStackedWidget()
        
        # Page 0: Raw Signal (no parameters)
        raw_page = QWidget()
        raw_layout = QVBoxLayout()
        raw_layout.addWidget(QLabel("No parameters required for raw signal"))
        raw_page.setLayout(raw_layout)
        self.param_stack.addWidget(raw_page)
        
        # Page 1: ARMA parameters
        arma_page = QWidget()
        arma_layout = QVBoxLayout()
        
        ar_layout = QHBoxLayout()
        ar_layout.addWidget(QLabel("AR Order (na):"))
        self.ar_order_spinbox = QSpinBox()
        self.ar_order_spinbox.setMinimum(1)
        self.ar_order_spinbox.setMaximum(50)
        self.ar_order_spinbox.setValue(TEXTURE_MODEL_CONFIG["arma"]["default_parameters"]["ar_order"])
        self.ar_order_spinbox.valueChanged.connect(self.on_parameter_changed)
        ar_layout.addWidget(self.ar_order_spinbox)
        ar_layout.addStretch()
        arma_layout.addLayout(ar_layout)
        
        ma_layout = QHBoxLayout()
        ma_layout.addWidget(QLabel("MA Order (nc):"))
        self.ma_order_spinbox = QSpinBox()
        self.ma_order_spinbox.setMinimum(1)
        self.ma_order_spinbox.setMaximum(50)
        self.ma_order_spinbox.setValue(TEXTURE_MODEL_CONFIG["arma"]["default_parameters"]["ma_order"])
        self.ma_order_spinbox.valueChanged.connect(self.on_parameter_changed)
        ma_layout.addWidget(self.ma_order_spinbox)
        ma_layout.addStretch()
        arma_layout.addLayout(ma_layout)
        
        arma_page.setLayout(arma_layout)
        self.param_stack.addWidget(arma_page)
        
        # Page 2: MFCC parameters
        mfcc_page = QWidget()
        mfcc_layout = QVBoxLayout()
        
        coeff_layout = QHBoxLayout()
        coeff_layout.addWidget(QLabel("Number of Coefficients:"))
        self.mfcc_coeffs_spinbox = QSpinBox()
        self.mfcc_coeffs_spinbox.setMinimum(1)
        self.mfcc_coeffs_spinbox.setMaximum(40)
        self.mfcc_coeffs_spinbox.setValue(TEXTURE_MODEL_CONFIG["mfcc"]["default_parameters"]["num_coefficients"])
        self.mfcc_coeffs_spinbox.valueChanged.connect(self.on_parameter_changed)
        coeff_layout.addWidget(self.mfcc_coeffs_spinbox)
        coeff_layout.addStretch()
        mfcc_layout.addLayout(coeff_layout)
        
        filters_layout = QHBoxLayout()
        filters_layout.addWidget(QLabel("Number of Filters:"))
        self.mfcc_filters_spinbox = QSpinBox()
        self.mfcc_filters_spinbox.setMinimum(10)
        self.mfcc_filters_spinbox.setMaximum(50)
        self.mfcc_filters_spinbox.setValue(TEXTURE_MODEL_CONFIG["mfcc"]["default_parameters"]["num_filters"])
        self.mfcc_filters_spinbox.valueChanged.connect(self.on_parameter_changed)
        filters_layout.addWidget(self.mfcc_filters_spinbox)
        filters_layout.addStretch()
        mfcc_layout.addLayout(filters_layout)
        
        frame_layout = QHBoxLayout()
        frame_layout.addWidget(QLabel("Frame Size (ms):"))
        self.mfcc_framesize_spinbox = QDoubleSpinBox()
        self.mfcc_framesize_spinbox.setMinimum(5.0)
        self.mfcc_framesize_spinbox.setMaximum(100.0)
        self.mfcc_framesize_spinbox.setValue(TEXTURE_MODEL_CONFIG["mfcc"]["default_parameters"]["frame_size"] * 1000)
        self.mfcc_framesize_spinbox.setSingleStep(1.0)
        self.mfcc_framesize_spinbox.valueChanged.connect(self.on_parameter_changed)
        frame_layout.addWidget(self.mfcc_framesize_spinbox)
        frame_layout.addStretch()
        mfcc_layout.addLayout(frame_layout)
        
        stride_layout = QHBoxLayout()
        stride_layout.addWidget(QLabel("Frame Stride (ms):"))
        self.mfcc_framestride_spinbox = QDoubleSpinBox()
        self.mfcc_framestride_spinbox.setMinimum(1.0)
        self.mfcc_framestride_spinbox.setMaximum(50.0)
        self.mfcc_framestride_spinbox.setValue(TEXTURE_MODEL_CONFIG["mfcc"]["default_parameters"]["frame_stride"] * 1000)
        self.mfcc_framestride_spinbox.setSingleStep(1.0)
        self.mfcc_framestride_spinbox.valueChanged.connect(self.on_parameter_changed)
        stride_layout.addWidget(self.mfcc_framestride_spinbox)
        stride_layout.addStretch()
        mfcc_layout.addLayout(stride_layout)
        
        mfcc_page.setLayout(mfcc_layout)
        self.param_stack.addWidget(mfcc_page)
        
        # Page 3: sPeak parameters
        speak_page = QWidget()
        speak_layout = QVBoxLayout()
        
        peaks_layout = QHBoxLayout()
        peaks_layout.addWidget(QLabel("Number of Peaks:"))
        self.speak_peaks_spinbox = QSpinBox()
        self.speak_peaks_spinbox.setMinimum(1)
        self.speak_peaks_spinbox.setMaximum(100)
        self.speak_peaks_spinbox.setValue(TEXTURE_MODEL_CONFIG["speak"]["default_parameters"]["num_peaks"])
        self.speak_peaks_spinbox.valueChanged.connect(self.on_parameter_changed)
        peaks_layout.addWidget(self.speak_peaks_spinbox)
        peaks_layout.addStretch()
        speak_layout.addLayout(peaks_layout)
        
        speak_page.setLayout(speak_layout)
        self.param_stack.addWidget(speak_page)
        
        # Page 4: sBeta parameters
        sbeta_page = QWidget()
        sbeta_layout = QVBoxLayout()
        
        peaks_layout = QHBoxLayout()
        peaks_layout.addWidget(QLabel("Number of Peaks:"))
        self.sbeta_peaks_spinbox = QSpinBox()
        self.sbeta_peaks_spinbox.setMinimum(3)
        self.sbeta_peaks_spinbox.setMaximum(50)
        self.sbeta_peaks_spinbox.setValue(TEXTURE_MODEL_CONFIG["sbeta"]["default_parameters"]["num_peaks"])
        self.sbeta_peaks_spinbox.valueChanged.connect(self.on_parameter_changed)
        peaks_layout.addWidget(self.sbeta_peaks_spinbox)
        peaks_layout.addStretch()
        sbeta_layout.addLayout(peaks_layout)
        
        alpha_layout = QHBoxLayout()
        alpha_layout.addWidget(QLabel("Alpha (initial):"))
        self.sbeta_alpha_spinbox = QDoubleSpinBox()
        self.sbeta_alpha_spinbox.setMinimum(0.1)
        self.sbeta_alpha_spinbox.setMaximum(20.0)
        self.sbeta_alpha_spinbox.setValue(TEXTURE_MODEL_CONFIG["sbeta"]["default_parameters"]["alpha_init"])
        self.sbeta_alpha_spinbox.setSingleStep(0.1)
        self.sbeta_alpha_spinbox.valueChanged.connect(self.on_parameter_changed)
        alpha_layout.addWidget(self.sbeta_alpha_spinbox)
        alpha_layout.addStretch()
        sbeta_layout.addLayout(alpha_layout)
        
        beta_layout = QHBoxLayout()
        beta_layout.addWidget(QLabel("Beta (initial):"))
        self.sbeta_beta_spinbox = QDoubleSpinBox()
        self.sbeta_beta_spinbox.setMinimum(0.1)
        self.sbeta_beta_spinbox.setMaximum(20.0)
        self.sbeta_beta_spinbox.setValue(TEXTURE_MODEL_CONFIG["sbeta"]["default_parameters"]["beta_init"])
        self.sbeta_beta_spinbox.setSingleStep(0.1)
        self.sbeta_beta_spinbox.valueChanged.connect(self.on_parameter_changed)
        beta_layout.addWidget(self.sbeta_beta_spinbox)
        beta_layout.addStretch()
        sbeta_layout.addLayout(beta_layout)
        
        freq_low_layout = QHBoxLayout()
        freq_low_layout.addWidget(QLabel("Freq Low (Hz):"))
        self.sbeta_freqlow_spinbox = QSpinBox()
        self.sbeta_freqlow_spinbox.setMinimum(10)
        self.sbeta_freqlow_spinbox.setMaximum(5000)
        self.sbeta_freqlow_spinbox.setValue(TEXTURE_MODEL_CONFIG["sbeta"]["default_parameters"]["freq_low"])
        self.sbeta_freqlow_spinbox.valueChanged.connect(self.on_parameter_changed)
        freq_low_layout.addWidget(self.sbeta_freqlow_spinbox)
        freq_low_layout.addStretch()
        sbeta_layout.addLayout(freq_low_layout)
        
        freq_high_layout = QHBoxLayout()
        freq_high_layout.addWidget(QLabel("Freq High (Hz):"))
        self.sbeta_freqhigh_spinbox = QSpinBox()
        self.sbeta_freqhigh_spinbox.setMinimum(100)
        self.sbeta_freqhigh_spinbox.setMaximum(10000)
        self.sbeta_freqhigh_spinbox.setValue(TEXTURE_MODEL_CONFIG["sbeta"]["default_parameters"]["freq_high"])
        self.sbeta_freqhigh_spinbox.valueChanged.connect(self.on_parameter_changed)
        freq_high_layout.addWidget(self.sbeta_freqhigh_spinbox)
        freq_high_layout.addStretch()
        sbeta_layout.addLayout(freq_high_layout)
        
        sbeta_page.setLayout(sbeta_layout)
        self.param_stack.addWidget(sbeta_page)
        
        # Page 5: Spectral Slope parameters
        slope_page = QWidget()
        slope_layout = QVBoxLayout()
        
        window_layout = QHBoxLayout()
        window_layout.addWidget(QLabel("Smoothing Window Size:"))
        self.slope_window_spinbox = QSpinBox()
        self.slope_window_spinbox.setMinimum(1)
        self.slope_window_spinbox.setMaximum(20)
        self.slope_window_spinbox.setValue(TEXTURE_MODEL_CONFIG["spectral_slope"]["default_parameters"]["window_size"])
        self.slope_window_spinbox.valueChanged.connect(self.on_parameter_changed)
        window_layout.addWidget(self.slope_window_spinbox)
        window_layout.addStretch()
        slope_layout.addLayout(window_layout)
        
        freqlow_layout = QHBoxLayout()
        freqlow_layout.addWidget(QLabel("Reference Freq Low (Hz):"))
        self.slope_freqlow_spinbox = QSpinBox()
        self.slope_freqlow_spinbox.setMinimum(5)
        self.slope_freqlow_spinbox.setMaximum(1000)
        self.slope_freqlow_spinbox.setValue(TEXTURE_MODEL_CONFIG["spectral_slope"]["default_parameters"]["ref_freq_low"])
        self.slope_freqlow_spinbox.valueChanged.connect(self.on_parameter_changed)
        freqlow_layout.addWidget(self.slope_freqlow_spinbox)
        freqlow_layout.addStretch()
        slope_layout.addLayout(freqlow_layout)
        
        freqhigh_layout = QHBoxLayout()
        freqhigh_layout.addWidget(QLabel("Reference Freq High (Hz):"))
        self.slope_freqhigh_spinbox = QSpinBox()
        self.slope_freqhigh_spinbox.setMinimum(100)
        self.slope_freqhigh_spinbox.setMaximum(10000)
        self.slope_freqhigh_spinbox.setValue(TEXTURE_MODEL_CONFIG["spectral_slope"]["default_parameters"]["ref_freq_high"])
        self.slope_freqhigh_spinbox.valueChanged.connect(self.on_parameter_changed)
        freqhigh_layout.addWidget(self.slope_freqhigh_spinbox)
        freqhigh_layout.addStretch()
        slope_layout.addLayout(freqhigh_layout)
        
        slope_page.setLayout(slope_layout)
        self.param_stack.addWidget(slope_page)
        
        params_layout.addWidget(self.param_stack)
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.apply_button = QPushButton("🔄 Apply Model")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_model)
        button_layout.addWidget(self.apply_button)
        
        self.export_button = QPushButton("💾 Export Model")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_model)
        button_layout.addWidget(self.export_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Connect radio signals now that param_stack exists
        for model_name, radio in self.radio_buttons.items():
            radio.toggled.connect(lambda checked, name=model_name: self.on_model_changed(name, checked))
    
    def set_recording(self, recording: Recording):
        """Set current recording and display its FFT."""
        self.current_recording = recording
        self.display_widget.set_original_recording(recording.data, recording.sample_rate)
        self.apply_button.setEnabled(True)
    
    def on_model_changed(self, model_name: str, checked: bool):
        """Handle model type change."""
        if not checked:
            return
        
        self.current_model_type = model_name
        
        # Switch parameter page
        model_index = {
            "Raw Signal": 0,
            "ARMA": 1,
            "MFCC": 2,
            "sPeak": 3,
            "sBeta": 4,
            "Spectral Slope": 5
        }
        
        self.param_stack.setCurrentIndex(model_index.get(model_name, 0))
        
        # If raw signal, apply immediately
        if model_name == "Raw Signal" and self.current_recording:
            self.apply_model()
    
    def on_parameter_changed(self):
        """Handle parameter value changes."""
        # Parameters changed, can reapply model
        pass
    
    def apply_model(self):
        """Apply current model with current parameters."""
        if not self.current_recording:
            return
        
        try:
            model = self._create_current_texture_model()
            parameters = model.encode(self.current_recording.data, self.current_recording.sample_rate)
            reconstructed = model.decode(parameters, self.current_recording.duration, self.current_recording.sample_rate)
            
            # Update display with reconstructed signal
            self.display_widget.update_model_display(reconstructed, self.current_model_type, parameters)
            self.export_button.setEnabled(True)
            
            # Emit signal
            self.model_updated.emit({
                "model_type": self.current_model_type,
                "parameters": parameters,
                "preprocessing_mode": self.preprocessing_combo.currentData(),
                "reconstructed": reconstructed,
                "original": self.current_recording.data
            })
            
        except Exception as e:
            print(f"Error applying model: {e}")

    def _create_current_texture_model(self):
        common = self._model_common_kwargs()
        if self.current_model_type == "ARMA":
            return create_texture_model("ar", ar_order=self.ar_order_spinbox.value(), **common)
        if self.current_model_type == "MFCC":
            return create_texture_model(
                "mfcc",
                num_coefficients=self.mfcc_coeffs_spinbox.value(),
                num_filters=self.mfcc_filters_spinbox.value(),
                frame_size=self.mfcc_framesize_spinbox.value() / 1000.0,
                frame_stride=self.mfcc_framestride_spinbox.value() / 1000.0,
                **common,
            )
        if self.current_model_type == "sPeak":
            return create_texture_model("speak", num_peaks=self.speak_peaks_spinbox.value(), **common)
        if self.current_model_type == "sBeta":
            return create_texture_model(
                "sbeta",
                num_peaks=self.sbeta_peaks_spinbox.value(),
                alpha_init=self.sbeta_alpha_spinbox.value(),
                beta_init=self.sbeta_beta_spinbox.value(),
                freq_low=self.sbeta_freqlow_spinbox.value(),
                freq_high=self.sbeta_freqhigh_spinbox.value(),
                **common,
            )
        if self.current_model_type == "Spectral Slope":
            return create_texture_model(
                "spectral_slope",
                freq_low=self.slope_freqlow_spinbox.value(),
                freq_high=self.slope_freqhigh_spinbox.value(),
                **common,
            )
        return create_texture_model("raw", **common)

    def _model_common_kwargs(self):
        return {
            "preprocessing_mode": self.preprocessing_combo.currentData()
        }

    
    def apply_arma_model(self) -> np.ndarray:
        """Apply ARMA model to current recording."""
        data = self.current_recording.data
        if data.ndim > 1:
            data = data[:, 0]
        
        ar_order = self.ar_order_spinbox.value()
        ma_order = self.ma_order_spinbox.value()
        N = len(data)
        
        try:
            # Fit ARIMA model (ARMA is ARIMA with d=0)
            model = ARIMA(data, order=(ar_order, 0, ma_order))
            fitted_model = model.fit()

            print(fitted_model.summary())
            
            # statsmodels returns coefficients WITHOUT leading 1, so we add it
            ar_params = fitted_model.arparams  # AR coefficients [a1, a2, ...]
            ma_params = fitted_model.maparams  # MA coefficients [b1, b2, ...]

            print(f"AR coefficients (without leading 1): {ar_params}"
                  f"\nMA coefficients (without leading 1): {ma_params}")
            
            # Build coefficient arrays with leading 1 
            AR_coeffs = np.concatenate([[1], -ar_params])  # [1, -a1, -a2, ...]
            MA_coeffs = np.concatenate([[1], ma_params])   # [1, b1, b2, ...]
            
            # Simulate using these coefficients 
            x_reconstructed = sp_signal.lfilter(MA_coeffs, AR_coeffs, np.random.randn(N))
            
            # Normalize (MATLAB: x_norm = x_reconstructed/max(abs(x_reconstructed)))
            x_norm = x_reconstructed / (np.max(np.abs(x_reconstructed)) + 1e-10)
            
            # Scale to original amplitude (MATLAB: max(abs(texture))*x_reconstructed)
            x_reconstructed = np.max(np.abs(data)) * x_reconstructed
            
            return x_reconstructed
            
        except Exception as e:
            print(f"ARMA model fitting failed: {e}")
            # Fallback to original data
            return data
    
    def apply_mfcc_model(self) -> np.ndarray:
        """Apply MFCC model (Mel-frequency cepstral coefficients)."""
        from scipy.fftpack import dct, idct
        
        data = self.current_recording.data
        if data.ndim > 1:
            data = data[:, 0]
        
        num_coeffs = self.mfcc_coeffs_spinbox.value()
        num_filters = self.mfcc_filters_spinbox.value()
        frame_size = self.mfcc_framesize_spinbox.value() / 1000.0  # Convert ms to seconds
        frame_stride = self.mfcc_framestride_spinbox.value() / 1000.0
        sample_rate = self.current_recording.sample_rate

        # Strict MATLAB-style constants/flow
        NFFT = int(TEXTURE_MODEL_CONFIG["mfcc"]["default_parameters"]["fft_size"])
        low_freq = TEXTURE_MODEL_CONFIG["mfcc"]["default_parameters"]["low_freq"]
        high_freq = TEXTURE_MODEL_CONFIG["mfcc"]["default_parameters"]["high_freq"]
        
        # Framing
        frame_length = int(round(frame_size * sample_rate))
        frame_step = int(round(frame_stride * sample_rate))

        frame_length = max(1, frame_length)
        frame_step = max(1, frame_step)
        num_frames = int(np.floor((len(data) - frame_length) / frame_step) + 1)
        if num_frames <= 0:
            num_frames = 1
            frame_length = min(frame_length, len(data))
        
        frames = np.zeros((num_frames, frame_length))
        for i in range(num_frames):
            start_idx = i * frame_step
            end_idx = min(start_idx + frame_length, len(data))
            chunk = data[start_idx:end_idx]
            frames[i, :len(chunk)] = chunk
        
        # Apply Hamming window
        hamming_window = np.hamming(frame_length)
        frames = frames * hamming_window
        
        # FFT and Power Spectrum
        mag_frames = np.abs(np.fft.fft(frames, n=NFFT, axis=1))
        pow_frames = (1.0 / NFFT) * (mag_frames ** 2)
        
        # Mel Filter Bank
        mel_low = 2595 * np.log10(1 + low_freq / 700.0)
        mel_high = 2595 * np.log10(1 + high_freq / 700.0)
        mel_points = np.linspace(mel_low, mel_high, num_filters + 2)
        hz_points = 700 * (10 ** (mel_points / 2595) - 1)
        bin_points = np.floor((NFFT + 1) * hz_points / sample_rate).astype(int)
        
        filter_bank = np.zeros((num_filters, int(np.floor(NFFT / 2 + 1))))
        for m in range(1, num_filters + 1):
            f_m_minus = bin_points[m - 1]
            f_m = bin_points[m]
            f_m_plus = bin_points[m + 1]
            
            for k in range(f_m_minus, f_m + 1):
                if k < filter_bank.shape[1]:
                    filter_bank[m - 1, k] = (k - f_m_minus) / (f_m - f_m_minus)

            for k in range(f_m, f_m_plus + 1):
                if k < filter_bank.shape[1]:
                    filter_bank[m - 1, k] = (f_m_plus - k) / (f_m_plus - f_m)
        
        # Apply filter bank
        filter_bank_energies = np.dot(pow_frames[:, :filter_bank.shape[1]], filter_bank.T)
        filter_bank_energies = np.log(filter_bank_energies + 1e-10)
        
        # DCT to get MFCCs
        mfccs = dct(filter_bank_energies, type=2, axis=1, norm='ortho')
        mfccs = mfccs[:, :num_coeffs]
        
        # === RECONSTRUCTION ===
        
        # Inverse DCT
        inv_filter_bank_energies = idct(mfccs, type=2, n=num_filters, axis=1, norm='ortho')
        
        # Convert back from log scale
        inv_power_spectrum = np.exp(inv_filter_bank_energies) @ np.linalg.pinv(filter_bank.T)
        
        # Reconstruct magnitude spectrum
        inv_magnitude_spectrum = np.sqrt(inv_power_spectrum * NFFT)
        
        # Random phase (phase is lost in MFCC extraction)
        random_phase = np.exp(1j * 2 * np.pi * np.random.rand(*inv_magnitude_spectrum.shape))
        
        # Construct complex spectrum (MATLAB style)
        complex_spectrum = inv_magnitude_spectrum * random_phase
        
        # Inverse FFT to get time-domain frames (MATLAB: real(ifft(..., NFFT, 2)))
        reconstructed_frames = np.real(np.fft.ifft(complex_spectrum, n=NFFT, axis=1))
        
        # Overlap-add reconstruction
        reconstructed_signal = np.zeros((num_frames - 1) * frame_step + frame_length)
        for i in range(num_frames):
            start_idx = i * frame_step
            end_idx = min(start_idx + frame_length, len(reconstructed_signal))
            frame_data = reconstructed_frames[i, :(end_idx - start_idx)]
            reconstructed_signal[start_idx:end_idx] += frame_data
        
        # Normalize
        reconstructed_signal = reconstructed_signal / (np.max(np.abs(reconstructed_signal)) + 1e-10)
        
        # Match power to original
        P1 = np.mean(data ** 2)
        P2 = np.mean(reconstructed_signal ** 2)
        alpha_power = np.sqrt(P1 / (P2 + 1e-10))
        reconstructed_signal = alpha_power * reconstructed_signal
        
        # Match length to original
        if len(reconstructed_signal) > len(data):
            reconstructed_signal = reconstructed_signal[:len(data)]
        elif len(reconstructed_signal) < len(data):
            reconstructed_signal = np.pad(reconstructed_signal, (0, len(data) - len(reconstructed_signal)))
        
        return reconstructed_signal
    
    def apply_speak_model(self) -> np.ndarray:
        """Apply sPeak model (peak-based spectral model)."""
        data = self.current_recording.data
        if data.ndim > 1:
            data = data[:, 0]
        
        peak_order = self.speak_peaks_spinbox.value()
        sample_rate = self.current_recording.sample_rate
        L = len(data)

        # Match MATLAB preprocessing:
        # texture_fft = fft(texture/L); texture_fft = texture_fft(2:L/2+1)
        texture_fft = np.fft.fft(data / L)
        texture_fft = texture_fft[1:L // 2 + 1]
        freq = sample_rate / L * np.arange(0, L // 2)

        # Sort magnitudes descending and enforce 20 Hz separation
        s_indices = np.argsort(np.abs(texture_fft))[::-1]
        s_peaks = np.abs(texture_fft)[s_indices]
        s_freq = freq[s_indices]

        spec_parameters = [[s_peaks[0], s_freq[0]]]
        for i in range(1, len(s_freq)):
            if s_freq[i] > (max(p[1] for p in spec_parameters) + 20):
                spec_parameters.append([s_peaks[i], s_freq[i]])
                if len(spec_parameters) >= peak_order:
                    break

        spec_parameters = np.array(spec_parameters)

        # Time-domain synthesis with cosine sum (same as MATLAB)
        t = np.arange(L) / sample_rate
        synth_signal = np.zeros(L)
        for i in range(spec_parameters.shape[0]):
            amp = spec_parameters[i, 0]
            f_hz = spec_parameters[i, 1]
            synth_signal += amp * np.cos(2 * np.pi * f_hz * t)

        # Power matching
        P1 = np.mean(data ** 2)
        P2 = np.mean(synth_signal ** 2)
        alpha = np.sqrt(P1 / (P2 + 1e-10))
        synth_signal = alpha * synth_signal

        return synth_signal
    
    def apply_sbeta_model(self) -> np.ndarray:
        """Apply sBeta model (Beta distribution spectral model)."""
        from scipy.stats import beta as beta_dist
        from scipy.optimize import minimize
        
        data = self.current_recording.data
        if data.ndim > 1:
            data = data[:, 0]
        
        num_peaks = self.sbeta_peaks_spinbox.value()
        alpha_init = self.sbeta_alpha_spinbox.value()
        beta_init = self.sbeta_beta_spinbox.value()
        freq_low = self.sbeta_freqlow_spinbox.value()
        freq_high = self.sbeta_freqhigh_spinbox.value()
        sample_rate = self.current_recording.sample_rate
        
        # Compute FFT (matching MATLAB: fft(texture/L))
        L = len(data)
        texture_fft = np.fft.fft(data / L)
        texture_fft = texture_fft[1:L//2+1]  # Single-sided FFT, skip DC
        freq = sample_rate / L * np.arange(0, L//2)
        
        # Extract spectral peaks with minimum frequency separation (matching MATLAB)
        sorted_indices = np.argsort(np.abs(texture_fft))[::-1]
        sPeaks = np.abs(texture_fft)[sorted_indices]
        sFreq = freq[sorted_indices]
        
        # Build specParameters with 20 Hz separation
        spec_parameters = [[sPeaks[0], sFreq[0]]]
        for i in range(1, len(sFreq)):
            max_existing_freq = max([p[1] for p in spec_parameters])
            if sFreq[i] > max_existing_freq + 20:  # Minimum 20 Hz separation
                spec_parameters.append([sPeaks[i], sFreq[i]])
                if len(spec_parameters) >= num_peaks:
                    break
        
        spec_parameters = np.array(spec_parameters)
        
        # Avoid log10(0) by using freq values > 0
        freq_nonzero = freq.copy()
        freq_nonzero[freq_nonzero == 0] = 1e-10
        normdFreq = np.log10(freq_nonzero) / np.max(np.log10(freq_nonzero))
        
        spec_freq_nonzero = spec_parameters[:, 1].copy()
        spec_freq_nonzero[spec_freq_nonzero == 0] = 1e-10
        normdspecParameters_mag = np.abs(spec_parameters[:, 0]) / np.max(np.abs(texture_fft))
        normdspecParameters_freq = np.log10(spec_freq_nonzero) / np.max(np.log10(freq_nonzero))
        
        # Fit Beta distribution 
        def obj_fun(params):
            alpha, beta_param = params
            if alpha <= 0 or beta_param <= 0:
                return 1e10
            fitted = beta_dist.pdf(normdspecParameters_freq, alpha, beta_param)
            return np.sum((normdspecParameters_mag - fitted) ** 2)
        
        result = minimize(obj_fun, [alpha_init, beta_init], method='Nelder-Mead')
        estimated_params = result.x
        alpha_fit, beta_fit = estimated_params
        
        # Generate fitted curve using all normalized frequencies
        y_fit = beta_dist.pdf(normdFreq, alpha_fit, beta_fit)
        
        # Apply rectangular window (matching MATLAB)
        w = np.zeros(len(freq))
        idx_low = np.argmin(np.abs(freq - freq_low))
        idx_high = np.argmin(np.abs(freq - freq_high))
        w[idx_low:idx_high] = 1
        
        # Create synthetic filter (matching MATLAB)
        synthFilt = w * y_fit
        synthFilt = synthFilt * np.max(np.abs(texture_fft))
        
        # Handle NaN values
        synthFilt[np.isnan(synthFilt)] = 0
        
        # Add random phase (matching MATLAB)
        random_phase = 2 * np.pi * np.random.rand(len(synthFilt))
        spectrum_half = synthFilt * np.exp(1j * random_phase)
        
        # Create full spectrum 
        N_half = len(spectrum_half)
        if N_half % 2 == 0:
            # Even: [spectrum_half, conj(spectrum_half(end-1:-1:2))]
            spectrum_full = np.concatenate([spectrum_half, np.conj(spectrum_half[-2:0:-1])])
        else:
            # Odd: [spectrum_half, conj(spectrum_half(end:-1:2))]
            spectrum_full = np.concatenate([spectrum_half, np.conj(spectrum_half[-1:0:-1])])
        
        # Inverse FFT (matching MATLAB: real(ifft(spectrum_full)))
        syn_signal = np.real(np.fft.ifft(spectrum_full))
        
        # Match power to original signal (matching MATLAB)
        P1 = np.mean(data ** 2)
        P2 = np.mean(syn_signal ** 2)
        alpha_power = np.sqrt(P1 / (P2 + 1e-10))
        syn_signal = alpha_power * syn_signal
        
        # Ensure correct length
        if len(syn_signal) > len(data):
            syn_signal = syn_signal[:len(data)]
        
        return syn_signal
    
    def apply_spectral_slope_model(self) -> np.ndarray:
        """Apply Spectral Slope model (roll-off based filter design)."""

        
        data = self.current_recording.data
        if data.ndim > 1:
            data = data[:, 0]
        
        window_size = self.slope_window_spinbox.value()
        ref_freq_low = self.slope_freqlow_spinbox.value()
        ref_freq_high = self.slope_freqhigh_spinbox.value()
        sample_rate = self.current_recording.sample_rate
        
        # Compute FFT
        N = len(data)
        fft_data = np.fft.fft(data/N) 
        fft_data = fft_data[1:N//2+1]  # Single-sided FFT
        freqs = sample_rate / N * np.arange(0, N//2)
        
        # Apply Gaussian smoothing
        smooth_magnitude = gaussian_filter1d(np.abs(fft_data), sigma=window_size)
        
        # Find peak frequency
        index_peak = np.argmax(smooth_magnitude)
        freq_peak = freqs[index_peak]
        mag_peak = smooth_magnitude[index_peak]
        
        # Find reference frequency indices
        index_low = np.argmin(np.abs(freqs - ref_freq_low))
        index_high = np.argmin(np.abs(freqs - ref_freq_high))
        
        # Calculate power spectral density (dB)
        psd = 10 * np.log10(1 / (N * sample_rate) * smooth_magnitude**2 + 1e-10)
        
        # Calculate roll-off rates
        roll_off_after = round(((psd[index_high] - psd[index_peak]) / 
                                np.log10(freqs[index_high] / (freqs[index_peak] + 1e-10))) / 20)
        roll_off_before = round(((psd[index_peak] - psd[index_low]) / 
                                 np.log10((freqs[index_peak] + 1e-10) / freqs[index_low])) / 20)
        
        # Design digital filter using bilinear transformation approximation
        omega_max = 2 * np.pi * freq_peak
        
        # Create filter coefficients (simplified approach using cascaded biquads)
        # Initialize with all-pass
        b_total = np.array([1.0])
        a_total = np.array([1.0])
        
        # Add lowpass stages (roll-off after peak)
        for i in range(abs(int(roll_off_after))):
            # First-order lowpass: H(s) = wc / (s + wc)
            # Bilinear transform: s = 2*Fs*(z-1)/(z+1)
            wc = omega_max
            # Normalized to Fs
            wc_normalized = wc / sample_rate
            # Bilinear coefficients
            b_lp = np.array([wc_normalized, wc_normalized])
            a_lp = np.array([1 + wc_normalized, wc_normalized - 1])
            # Cascade
            b_total = np.convolve(b_total, b_lp)
            a_total = np.convolve(a_total, a_lp)
        
        # Add highpass stages (roll-off before peak)
        for i in range(abs(int(roll_off_before))):
            # First-order highpass: H(s) = s / (s + wc)
            wc = omega_max
            wc_normalized = wc / sample_rate
            # Bilinear coefficients
            b_hp = np.array([1, -1])
            a_hp = np.array([1 + wc_normalized, wc_normalized - 1])
            # Cascade
            b_total = np.convolve(b_total, b_hp)
            a_total = np.convolve(a_total, a_hp)
        
        # Normalize filter
        b_total = b_total / a_total[0]
        a_total = a_total / a_total[0]
        
        # Generate white noise and filter
        white_noise = np.random.randn(N)
        filtered_signal = sp_signal.lfilter(b_total, a_total, white_noise)
        
        # Match power to original signal
        P1 = np.mean(data ** 2)
        P2 = np.mean(filtered_signal ** 2)
        alpha_power = np.sqrt(P1 / (P2 + 1e-10))
        filtered_signal = alpha_power * filtered_signal
        
        return filtered_signal
    
    def export_model(self):
        """Export model parameters."""
        if not self.current_recording:
            return
        
        print(f"Exporting {self.current_model_type} model parameters...")
        # TODO: Implement file save dialog and parameter export
