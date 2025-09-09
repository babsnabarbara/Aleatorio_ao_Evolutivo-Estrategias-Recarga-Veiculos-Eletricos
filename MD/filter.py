def copy_lines_after_trip(input_filename, output_filename, lines_to_copy):
    with open(input_filename, 'r') as input_file, open(output_filename, 'w') as output_file:
        lines_remaining = lines_to_copy

        for line in input_file:
            if lines_remaining >= 0:
                output_file.write(line)
            
            if '<trip' in line and lines_remaining >= 0:
                lines_remaining -= 1
        output_file.write("</routes>")
    print(f"Processing complete. Output written to {output_filename}")

# Specify the input and output filenames
input_filename = 'input.xml'
output_filename = 'output.xml'

# Specify the number of lines to copy after each <trip> tag
lines_to_copy = 2000

# Call the function to copy lines after each <trip> tag
copy_lines_after_trip("../input/cologne6to8ORIGINAL.trips.xml", "../input/cologne6to8.trips.xml", lines_to_copy)
