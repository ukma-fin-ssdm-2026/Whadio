import { TextField, type TextFieldProps } from "@mui/material";
import {
  Controller,
  type FieldPathByValue,
  type FieldValues,
  type UseControllerProps,
} from "react-hook-form";

type FormTextFieldProps<
  TValues extends FieldValues,
  TName extends FieldPathByValue<TValues, string>,
  TTransformed,
> = Required<Pick<UseControllerProps<TValues, TName, TTransformed>, "control" | "name">> &
  Omit<TextFieldProps, "name" | "value" | "defaultValue" | "onChange" | "onBlur" | "error">;

export function FormTextField<
  TValues extends FieldValues,
  TName extends FieldPathByValue<TValues, string>,
  TTransformed,
>({ control, name, helperText, ...props }: FormTextFieldProps<TValues, TName, TTransformed>) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field: { ref, ...field }, fieldState: { error } }) => (
        <TextField
          {...props}
          {...field}
          inputRef={ref}
          error={Boolean(error)}
          helperText={error?.message ?? helperText}
        />
      )}
    />
  );
}
