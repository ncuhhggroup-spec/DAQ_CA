%% HHG Energy Calculation with Wavelength Calibration
clear all; close all;

%% 1. Physics Constants & Configuration
% Spectrometer Parameters (from previous turn)
d_gt = 278; m_diff = 1; gamma_toroi = 3.75; R = 1926; px = 13.5e-3; x0 = 963;
theta_0 = 12; % Set your central grating angle here (e.g., from CSV)

filePattern = 'HHG_33_*.txt';

% --- Background Fitting Definition ---
% Rectangle to EXCLUDE from the background model (SigBox) [x_min, x_max, y_min, y_max]
sigBox = [400, 2048, 130, 512]; 

% --- Precise Integration Points (4 corners for Polygon in Pixels) ---
sigX = [601, 1743, 2048, 566]; 
sigY = [157, 157, 512, 382];

%% 2. Load and Prepare Calibration
files = dir(fullfile(pwd, filePattern));
numFiles = length(files);
if numFiles == 0; error('No files found matching %s', filePattern); end

sample = load(files(1).name);
[rows, cols] = size(sample);
[X, Y] = meshgrid(1:cols, 1:rows);

% --- Wavelength Calibration Logic ---
delta_theta = atan2d(((1:cols) - x0) * px, R * sind(gamma_toroi)); 
lambda_vec = (d_gt / m_diff) * sind(gamma_toroi) * (sind(theta_0) + sind(theta_0 + delta_theta));

% Create the Polygon Mask (Logic remains in pixel space for indexing)
sigMask = poly2mask(sigX, sigY, rows, cols);

% Pre-allocate
polyEnergies = zeros(numFiles, 1);
allCorrectedShots = zeros(numFiles, rows, cols);

%% 3. Processing Loop
fprintf('Processing %d shots with Wavelength Calibration...\n', numFiles);
for i = 1:numFiles
    data = load(files(i).name);
    
    % --- Step A: 2D Background Fit ---
    isBackground = ~(X >= sigBox(1) & X <= sigBox(2) & Y >= sigBox(3) & Y <= sigBox(4));
    ft = fittype('poly41'); 
    fittedModel = fit([X(isBackground), Y(isBackground)], data(isBackground), ft);
    fullBK = fittedModel(X, Y);
    
    % --- Step B: Subtraction & Integration ---
    corrected = data - fullBK;
    allCorrectedShots(i, :, :) = corrected; 
    
    polyEnergies(i) = sum(corrected(sigMask));
end

%% 4. Visualizations & PDF Output
% --- Figure 1: Calibration & Mask Check ---
fig1 = figure('Name', 'Calibration_Check', 'Color', 'w', 'Units', 'inches', 'Position', [1 1 12 5]);
tlo1 = tiledlayout(1, 2, 'Padding', 'compact');

% Plot 1: Raw Data with Wavelength X-axis
nexttile;
imagesc(lambda_vec, 1:rows, sample); hold on; colormap(turbo); colorbar;
title('Raw Data (Wavelength Axis)');
xlabel('Wavelength (nm)'); ylabel('Pixel (Y)');

% Plot 2: Corrected with Mask
nexttile;
imagesc(lambda_vec, 1:rows, squeeze(allCorrectedShots(1,:,:))); hold on; colorbar;
% Convert sigX pixels to lambda for plotting the boundary
sigLambda = interp1(1:cols, lambda_vec, sigX);
plot([sigLambda, sigLambda(1)], [sigY, sigY(1)], 'w', 'LineWidth', 2); 
title('Corrected Shot 1 + Integration Mask');
xlabel('Wavelength (nm)');
clim([0, prctile(corrected(:), 99.5)]);

exportgraphics(tlo1, 'HHG_Wavelength_Mask_Check.pdf', 'ContentType', 'vector');

% --- Figure 2: Average Corrected Image ---
avgCorrected = squeeze(mean(allCorrectedShots, 1));
fig2 = figure('Name', 'Average_Cleaned_Signal', 'Color', 'w', 'Units', 'inches', 'Position', [1 1 8 6]);
imagesc(lambda_vec, 1:rows, avgCorrected); colormap(turbo); colorbar;
hold on; plot([sigLambda, sigLambda(1)], [sigY, sigY(1)], 'w--', 'LineWidth', 1);
title(['Average HHG Signal (\theta_0 = ', num2str(theta_0), '^\circ)']);
xlabel('Wavelength (nm)'); ylabel('Pixels (Y)');
exportgraphics(fig2, 'HHG_Average_Corrected_Wavelength.pdf', 'ContentType', 'vector');

%% 5. Statistical Output
fprintf('\n--- Analysis Results ---\n');
fprintf('Mean Energy in Mask: %.4e\n', mean(polyEnergies));
fprintf('Stability (RMS/Mean): %.2f%%\n', (std(polyEnergies)/mean(polyEnergies))*100);